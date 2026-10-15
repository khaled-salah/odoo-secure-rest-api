"""Shared plumbing for every REST endpoint.

One decorator (`api_endpoint`) gives each route the same behaviour:

* bearer-token authentication and scope checks,
* switching the environment to the client's technical user (no sudo),
* one JSON error format,
* rolling back the transaction on any error, so a failed request never
  commits half of its writes.
"""

import functools
import json
import logging

import pydantic

from odoo import exceptions
from odoo.http import Response, request

from ..services.tokens import TokenError, decode_token

_logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024
JSON_HEADERS = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]


class ApiError(Exception):
    def __init__(self, status, code, message, details=None, headers=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or []


def json_response(payload, status=200, headers=None):
    return Response(
        json.dumps(payload, default=str),
        status=status,
        headers=JSON_HEADERS + list(headers or []),
    )


def error_response(status, code, message, details=None, headers=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return json_response(body, status=status, headers=headers)


def pydantic_details(exc):
    # Drop "input"/"url": never echo submitted values (could be secrets/PII) back.
    return [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
        for err in exc.errors(include_url=False, include_input=False)
    ]


def read_json_body():
    raw = request.httprequest.get_data(cache=False)
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large", "Request body is too large.")
    try:
        data = json.loads(raw or b"{}")
    except ValueError as exc:
        raise ApiError(400, "invalid_json", "Request body is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_json", "Request body must be a JSON object.")
    return data


def authenticate(required_scope):
    header = request.httprequest.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    challenge = [("WWW-Authenticate", 'Bearer realm="odoo"')]
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "unauthorized", "Missing bearer token.", headers=challenge)
    try:
        claims = decode_token(request.env, token.strip())
    except TokenError as exc:
        raise ApiError(401, "unauthorized", str(exc), headers=challenge) from exc

    client = (
        request.env["rest.api.client"].sudo().search([("client_id", "=", claims["sub"])], limit=1)
    )
    # Re-check the client on every call: archiving it revokes live tokens at once.
    if not client or not client.user_id.active:
        raise ApiError(401, "unauthorized", "Client is disabled.", headers=challenge)

    token_scopes = set(claims.get("scope", "").split())
    if required_scope not in token_scopes or required_scope not in client.get_scopes():
        raise ApiError(403, "insufficient_scope", f"Scope '{required_scope}' is required.")

    request.update_env(user=client.user_id.id)
    return client


def api_endpoint(scope=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                if scope:
                    authenticate(scope)
                return func(self, *args, **kwargs)
            except ApiError as exc:
                request.env.cr.rollback()
                return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)
            except pydantic.ValidationError as exc:
                request.env.cr.rollback()
                return error_response(
                    422, "validation_error", "Invalid request data.", pydantic_details(exc)
                )
            except exceptions.AccessError:
                request.env.cr.rollback()
                return error_response(403, "forbidden", "Access denied.")
            except (exceptions.UserError, exceptions.ValidationError) as exc:
                request.env.cr.rollback()
                return error_response(400, "business_error", str(exc))
            except Exception:
                request.env.cr.rollback()
                _logger.exception("Unhandled error in REST endpoint %s", func.__name__)
                return error_response(500, "internal_error", "Internal server error.")

        return wrapper

    return decorator
