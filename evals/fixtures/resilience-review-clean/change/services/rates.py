"""FX rates for pricing carts in the shopper's currency.

The scheduler calls `refresh_rates` every 10 minutes; request handlers only
read the cached table through `rate`, so a failed refresh keeps serving the
previous rates.
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

RATES_URL = "https://fx.internal/api/v2/rates"

# The rates fetch is an idempotent GET, so transient upstream failures are
# retried: at most 3 retries, exponential backoff with jitter, capped at 10s.
# Retry-After is ignored because urllib3 sleeps for whatever it says, with no
# cap; a failed refresh just keeps the cached rates until the next run.
_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    backoff_jitter=0.5,
    backoff_max=10,
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=False,
)

_rates: dict[str, float] = {"USD": 1.0}


def refresh_rates() -> None:
    global _rates
    try:
        with requests.Session() as session:
            session.mount("https://", HTTPAdapter(max_retries=_RETRY))
            response = session.get(RATES_URL, timeout=(3, 10))
            response.raise_for_status()
            _rates = response.json()
    except requests.RequestException:
        log.warning("fx rate refresh failed; keeping previous rates", exc_info=True)


def rate(currency: str) -> float:
    return _rates[currency]
