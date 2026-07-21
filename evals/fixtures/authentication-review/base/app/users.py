from werkzeug.security import generate_password_hash

# Placeholder store; real deployments load users from the database.
_USERS: dict[str, str] = {}

# Verifying against a dummy hash keeps response time uniform for
# unknown usernames.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def password_hash(username: str) -> str:
    return _USERS.get(username, _DUMMY_HASH)
