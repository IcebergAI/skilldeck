"""The running club's website and its JSON API (web and mobile clients)."""

import os

import segment.analytics as analytics
from flask import Flask, jsonify, request, session

import directory
from auth import login_required
from db import add_race_entry, get_user, has_consent

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
analytics.write_key = os.environ["SEGMENT_WRITE_KEY"]
app.register_blueprint(directory.bp)


@app.before_request
def record_page_view():
    """Feed the growth dashboard: one page event per request from a member.

    Like the race-entry event, it is sent only for members who consented to
    analytics, keyed on their random analytics ID, and carries only the page.
    """
    if "user_id" not in session or request.path.startswith("/static/"):
        return
    if not has_consent(session["user_id"], "analytics"):
        return
    user = get_user(session["user_id"])
    if user is None:
        return
    analytics.page(
        user_id=user["analytics_id"],
        name=request.endpoint,
        properties={"path": request.path},
    )


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
