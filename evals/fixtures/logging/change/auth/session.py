import logging

logger = logging.getLogger(__name__)


def start_session(user, token_store):
    token = token_store.issue(user.id)
    logger.info("session started", extra={"user_id": user.id})
    return token


def login(form, remote_addr, users, token_store):
    user = users.authenticate(form["username"], form["password"])
    if user is None:
        logger.warning("login failed for %s from %s", form["username"], remote_addr)
        return None
    logger.info("login succeeded", extra={"user_id": user.id, "ip": remote_addr})
    return start_session(user, token_store)
