"""Sign in with the corporate identity provider (OAuth 2.0 code flow)."""

import os

import requests
from flask import Blueprint, redirect, request, session

bp = Blueprint("sso", __name__)

AUTHORIZE_URL = "https://idp.example.com/oauth/authorize"
TOKEN_URL = "https://idp.example.com/oauth/token"
USERINFO_URL = "https://idp.example.com/oauth/userinfo"
CLIENT_ID = os.environ["SSO_CLIENT_ID"]
REDIRECT_URI = "https://app.example.com/sso/callback"


@bp.get("/sso/login")
def sso_login():
    return redirect(
        f"{AUTHORIZE_URL}?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid+profile+email"
    )


@bp.get("/sso/callback")
def sso_callback():
    code = request.args["code"]
    token = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=10,
    ).json()
    profile = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=10,
    ).json()
    session.clear()
    session["user"] = profile["email"]
    return redirect("/me")
