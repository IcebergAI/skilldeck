"""Member directory: lets members look each other up to arrange group runs."""

from flask import Blueprint, abort, jsonify

from auth import login_required
from db import get_user

bp = Blueprint("directory", __name__)

# What another member may see. Contact details, date of birth, and the
# national ID stay private: members swap numbers themselves if they want to.
PUBLIC_FIELDS = ("id", "display_name", "bio", "avatar_url")


@bp.get("/api/members/<int:member_id>")
@login_required
def member_profile(member_id):
    member = get_user(member_id)
    if member is None:
        abort(404)
    return jsonify({field: member[field] for field in PUBLIC_FIELDS})
