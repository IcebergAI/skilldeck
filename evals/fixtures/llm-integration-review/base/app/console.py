"""The agent console: the internal app support staff use to work tickets."""

import os

from flask import Flask, abort, jsonify

from auth import require_staff
from tickets import get_ticket

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]


@app.get("/tickets/<int:ticket_id>")
@require_staff
def show_ticket(ticket_id):
    ticket = get_ticket(ticket_id)
    if ticket is None:
        abort(404)
    return jsonify(ticket)
