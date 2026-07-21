import os

from flask import Flask, abort, jsonify, session

import saml_acs

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.register_blueprint(saml_acs.bp)


@app.get("/me")
def me():
    if "user" not in session:
        abort(401)
    return jsonify(user=session["user"])
