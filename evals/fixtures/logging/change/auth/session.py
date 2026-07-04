import logging

logger = logging.getLogger(__name__)


def start_session(user, token_store):
    token = token_store.issue(user.id)
    logger.info("session started", extra={"user_id": user.id})
    return token


def validate_token(user, token, token_store):
    if not token_store.check(user.id, token):
        logger.warning(f"auth failed for user {user.id} with token {token}")
        return False
    return True
