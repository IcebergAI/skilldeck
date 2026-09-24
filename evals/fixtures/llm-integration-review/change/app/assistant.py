"""Drafts a reply to a support ticket for the staff member working it.

The assistant checks the order's status on the order-service host before it
drafts, so replies quote real shipping data instead of guesses.
"""

import json
import subprocess

from flask import Blueprint, abort, jsonify
from openai import OpenAI

from auth import require_staff
from tickets import get_ticket

bp = Blueprint("assistant", __name__)
client = OpenAI(timeout=30)

MODEL = "gpt-4.1"
INSTRUCTIONS = (
    "You are Acme's support assistant. Draft a short, friendly reply to the "
    "customer's ticket. Before promising a delivery date, check the order with "
    "the run_diagnostic tool, e.g. `orderctl status <order-id>`."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_diagnostic",
            "description": "Run a diagnostic on the order-service host.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


def run_diagnostic(command):
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=20
    )
    return result.stdout + result.stderr


@bp.post("/tickets/<int:ticket_id>/draft-reply")
@require_staff
def draft_reply(ticket_id):
    ticket = get_ticket(ticket_id)
    if ticket is None:
        abort(404)
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": f"{ticket['subject']}\n\n{ticket['body']}"},
    ]
    while True:
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return jsonify({"draft": message.content})
        messages.append(message)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": run_diagnostic(args["command"]),
                }
            )
