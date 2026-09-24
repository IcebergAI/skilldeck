import os

from flask import Flask, abort, jsonify, request, send_file, session

import db

app = Flask(__name__)

DOCUMENTS_DIR = "/srv/orders/documents"


@app.get("/orders/<int:order_id>")
def get_order(order_id):
    order = db.get_order(order_id, user_id=session["user_id"])
    if order is None:
        abort(404)
    return jsonify(order.as_dict())


@app.get("/orders/<int:order_id>/documents")
def get_order_document(order_id):
    order = db.get_order(order_id, user_id=session["user_id"])
    if order is None:
        abort(404)
    name = request.args.get("name", "invoice.pdf")
    return send_file(os.path.join(DOCUMENTS_DIR, str(order.id), name))
