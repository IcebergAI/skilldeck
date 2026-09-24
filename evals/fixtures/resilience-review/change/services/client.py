import requests

ENRICH_URL = "https://enrich.internal/api/v1/profile"
SHIPPING_URL = "https://shipping.internal/api/v1/shipments"


def fetch_profile(session, user_id):
    response = session.get(f"{ENRICH_URL}/{user_id}", timeout=(3, 10))
    response.raise_for_status()
    return response.json()


def create_shipment(session, order_id, address):
    for attempt in range(5):
        try:
            response = session.post(
                SHIPPING_URL,
                json={"order_id": order_id, "address": address},
                timeout=(3, 10),
            )
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 4:
                raise
    response.raise_for_status()
    return response.json()["shipment_id"]
