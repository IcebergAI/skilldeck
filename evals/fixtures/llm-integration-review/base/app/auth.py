from functools import wraps

from flask import abort, session


def require_staff(view):
    """Only signed-in support staff may use the agent console."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "staff":
            abort(403)
        return view(*args, **kwargs)

    return wrapper
