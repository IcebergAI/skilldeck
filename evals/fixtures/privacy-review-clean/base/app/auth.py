from functools import wraps

from flask import abort, session


def login_required(view):
    """Only signed-in club members may use the site's API."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            abort(401)
        return view(*args, **kwargs)

    return wrapper
