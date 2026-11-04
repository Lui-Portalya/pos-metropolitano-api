import hashlib
import secrets

import bcrypt

BCRYPT_COST = 10


def _pw_bytes(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes. bcryptjs (the Node app) silently
    # truncates, the `bcrypt` package >= 5 raises; truncate so both agree.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt(rounds=BCRYPT_COST)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), password_hash.encode("ascii"))
    except ValueError:  # malformed hash in the DB
        return False


# Compared against when the username is unknown, so response time doesn't reveal it.
DUMMY_HASH = hash_password(secrets.token_hex(16))


def new_token() -> str:
    """Raw session token: 32 random bytes, hex encoded (same as the web app)."""
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest; only this is stored in `sessions.token_hash`."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
