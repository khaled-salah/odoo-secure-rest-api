from odoo import fields, http
from odoo.http import request

from ..models.api_client import hash_secret, verify_secret
from ..schemas import TokenRequest, TokenResponse
from ..services.tokens import issue_token
from .base import ApiError, api_endpoint, json_response, read_json_body

DUMMY_HASH = hash_secret("timing-equalizer")


class RestApiAuthController(http.Controller):
    @http.route(
        "/api/v1/auth/token",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @api_endpoint()
    def token(self, **_kwargs):
        payload = TokenRequest.model_validate(read_json_body())

        client = (
            request.env["rest.api.client"]
            .sudo()
            .search([("client_id", "=", payload.client_id)], limit=1)
        )
        # Same error, and roughly the same time, for "unknown client" and
        # "wrong secret", so callers can't probe which client IDs exist.
        if client:
            valid = client.check_secret(payload.client_secret)
        else:
            verify_secret(payload.client_secret, DUMMY_HASH)
            valid = False
        if not valid or not client.user_id.active:
            raise ApiError(401, "invalid_client", "Invalid client credentials.")

        token, expires_in, scope = issue_token(request.env, client)
        client.last_token_at = fields.Datetime.now()
        body = TokenResponse(access_token=token, expires_in=expires_in, scope=scope)
        return json_response(body.model_dump())
