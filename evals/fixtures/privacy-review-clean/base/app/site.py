"""The running club's website and its JSON API (web and mobile clients)."""

import os

import segment.analytics as analytics
from flask import Flask, jsonify, session

from auth import login_required
from db import add_race_entry, get_user, has_consent

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
analytics.write_key = os.environ["SEGMENT_WRITE_KEY"]


@app.get("/api/me")
@login_required
def me():
    """The signed-in member's own account, for the settings page."""
    return jsonify(get_user(session["user_id"]))


@app.post("/api/races/<int:race_id>/entries")
@login_required
def enter_race(race_id):
    user = get_user(session["user_id"])
    add_race_entry(race_id, user["id"])
    if has_consent(user["id"], "analytics"):
        analytics.track(
            user_id=user["analytics_id"],
            event="Race Entered",
            properties={"race_id": race_id},
        )
    return ("", 204)
