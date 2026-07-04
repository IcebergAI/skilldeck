import requests

ENRICH_URL = "https://enrich.internal/api/v1/profile"


def fetch_profile(session, user_id):
    response = session.get(f"{ENRICH_URL}/{user_id}", timeout=(3, 10))
    response.raise_for_status()
    return response.json()


def fetch_recommendations(user_id):
    response = requests.get(f"https://recs.internal/api/v1/users/{user_id}")
    response.raise_for_status()
    return response.json()
