"""FX rates for pricing carts in the shopper's currency.

The scheduler calls `refresh_rates` every 10 minutes; request handlers only
read the cached table through `rate`, so a failed refresh keeps serving the
previous rates.
"""

import logging

import requests

log = logging.getLogger(__name__)

RATES_URL = "https://fx.internal/api/v2/rates"

_rates: dict[str, float] = {"USD": 1.0}


def refresh_rates() -> None:
    global _rates
    try:
        response = requests.get(RATES_URL)
        response.raise_for_status()
        _rates = response.json()
    except requests.RequestException:
        log.warning("fx rate refresh failed; keeping previous rates", exc_info=True)


def rate(currency: str) -> float:
    return _rates[currency]
