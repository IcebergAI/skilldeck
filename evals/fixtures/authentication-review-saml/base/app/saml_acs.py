"""SAML assertion consumer service for IdP sign-in."""

import base64

from flask import Blueprint, abort, redirect, request, session
from signxml import XMLVerifier

import idp_config

bp = Blueprint("saml", __name__)

NS = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"}


@bp.post("/saml/acs")
def acs():
    document = base64.b64decode(request.form["SAMLResponse"])
    # Verify the signature and work only with the signed subtree from here on.
    verified = (
        XMLVerifier().verify(document, x509_cert=idp_config.IDP_CERT).signed_xml
    )
    audience = verified.findtext(".//saml:Audience", namespaces=NS)
    if audience != idp_config.SP_ENTITY_ID:
        abort(403)
    name_id = verified.findtext(".//saml:Subject/saml:NameID", namespaces=NS)
    if not name_id:
        abort(403)
    session.clear()
    session["user"] = name_id
    return redirect("/me")
