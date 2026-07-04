import logging

logger = logging.getLogger(__name__)


def start_session(user, token_store):
    token = token_store.issue(user.id)
    logger.info("session started", extra={"user_id": user.id})
    return token
