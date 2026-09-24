"""The agent console: the internal app support staff use to work tickets."""

import os

from flask import Flask, abort, jsonify, request, session
from flask_limiter import Limiter

from auth import require_staff
from tickets import ALLOWED_TAGS, add_ticket_tag, get_ticket

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
# keyed per staff member rather than per IP: the whole office shares one proxy
limiter = Limiter(key_func=lambda: str(session.get("user_id", "")), app=app)


@app.get("/tickets/<int:ticket_id>")
@require_staff
def show_ticket(ticket_id):
    ticket = get_ticket(ticket_id)
    if ticket is None:
        abort(404)
    return jsonify(ticket)


@app.post("/tickets/<int:ticket_id>/tags")
@require_staff
def add_tag(ticket_id):
    tag = (request.get_json(silent=True) or {}).get("tag")
    if tag not in ALLOWED_TAGS:
        abort(400)
    if get_ticket(ticket_id) is None:
        abort(404)
    add_ticket_tag(ticket_id, tag)
    return "", 204
