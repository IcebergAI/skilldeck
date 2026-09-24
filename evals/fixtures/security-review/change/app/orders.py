from flask import Flask, abort, jsonify, request, session

import db

app = Flask(__name__)


@app.get("/orders/<int:order_id>")
def get_order(order_id):
    order = db.get_order(order_id, user_id=session["user_id"])
    if order is None:
        abort(404)
    return jsonify(order.as_dict())


@app.patch("/orders/<int:order_id>")
def update_order(order_id):
    order = db.get_order(order_id, user_id=session["user_id"])
    if order is None:
        abort(404)
    changes = request.get_json()
    order = db.update_order(order.id, **changes)
    return jsonify(order.as_dict())
