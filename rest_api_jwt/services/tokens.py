"""JWT issuing and verification.

Kept free of HTTP concerns so it can be unit-tested and reused by other
controllers.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from ..hooks import JWT_SECRET_PARAM

ALGORITHM = "HS256"
AUDIENCE = "odoo-rest-api"
LEEWAY_SECONDS = 10


class TokenError(Exception):
    """Raised when a bearer token is missing, malformed, expired or revoked."""


def _signing_key(env):
    key = env["ir.config_parameter"].sudo().get_param(JWT_SECRET_PARAM)
    if not key:
        raise TokenError("API signing key is not configured")
    return key


def issue_token(env, client):
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=client.token_ttl_minutes)
    claims = {
        "iss": env.cr.dbname,
        "aud": AUDIENCE,
        "sub": client.client_id,
        "scope": " ".join(client.get_scopes()),
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, _signing_key(env), algorithm=ALGORITHM)
    return token, int(ttl.total_seconds()), claims["scope"]


def decode_token(env, token):
    try:
        return jwt.decode(
            token,
            _signing_key(env),
            algorithms=[ALGORITHM],  # never trust the token's own "alg" header
            audience=AUDIENCE,
            issuer=env.cr.dbname,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
