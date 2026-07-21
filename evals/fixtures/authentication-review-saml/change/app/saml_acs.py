"""SAML assertion consumer service for IdP sign-in."""

import base64

from flask import Blueprint, abort, redirect, request, session
from lxml import etree
from signxml import XMLVerifier

import idp_config

bp = Blueprint("saml", __name__)

NS = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"}

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


@bp.post("/saml/acs")
def acs():
    document = base64.b64decode(request.form["SAMLResponse"])
    # Check the response signature, then pull out the fields we need.
    XMLVerifier().verify(document, x509_cert=idp_config.IDP_CERT)
    tree = etree.fromstring(document, parser=_PARSER)
    assertion = tree.find(".//saml:Assertion", NS)
    if assertion is None:
        abort(403)
    name_id = assertion.findtext(".//saml:NameID", namespaces=NS)
    if not name_id:
        abort(403)
    session.clear()
    session["user"] = name_id
    return redirect("/me")
