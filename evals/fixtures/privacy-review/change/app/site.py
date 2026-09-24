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

    The mobile app sends the phone's current fix in X-Geo-Lat / X-Geo-Lon so
    the dashboard can map where members browse from.
    """
    if "user_id" not in session or request.path.startswith("/static/"):
        return
    user = get_user(session["user_id"])
    analytics.page(
        user_id=user["email"],
        name=request.endpoint,
        properties={
            "path": request.path,
            "email": user["email"],
            "lat": request.headers.get("X-Geo-Lat"),
            "lon": request.headers.get("X-Geo-Lon"),
        },
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
