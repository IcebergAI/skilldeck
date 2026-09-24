import os

from flask import Flask, abort, jsonify, session

import db

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.get("/documents/<int:doc_id>")
def get_document(doc_id):
    if "user_id" not in session:
        abort(401)
    row = db.query_one(
        "SELECT id, title, body FROM documents WHERE id = ? AND owner_id = ?",
        (doc_id, session["user_id"]),
    )
    if row is None:
        abort(404)
    return jsonify(dict(row))
