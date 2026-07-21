import os

from flask import Flask, abort, jsonify, request, session
from werkzeug.security import check_password_hash

import users

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.post("/login")
def login():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    stored_hash = users.password_hash(username)
    if not check_password_hash(stored_hash, password):
        abort(401, "Invalid username or password.")
    session.clear()
    session["user"] = username
    return jsonify(ok=True)


@app.get("/me")
def me():
    if "user" not in session:
        abort(401)
    return jsonify(user=session["user"])
