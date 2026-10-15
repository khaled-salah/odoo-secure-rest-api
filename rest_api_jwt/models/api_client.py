import hashlib
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PBKDF2_ITERATIONS = 260_000
SCOPES = ("leads:read", "leads:write")


def hash_secret(secret, salt=None, iterations=PBKDF2_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_secret(secret, stored):
    try:
        algo, iterations, salt, _digest = stored.split("$")
    except (AttributeError, ValueError):
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hash_secret(secret, salt=salt, iterations=int(iterations))
    return hmac.compare_digest(candidate, stored)


class RestApiClient(models.Model):
    """An external system allowed to call the REST API.

    Each client authenticates with a client_id / client_secret pair (OAuth2
    client-credentials style). Requests are executed as `user_id`, so normal
    Odoo access rights and record rules apply: the API never runs as sudo.
    """

    _name = "rest.api.client"
    _description = "REST API Client"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    client_id = fields.Char(
        string="Client ID",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: secrets.token_urlsafe(18),
    )
    secret_hash = fields.Char(copy=False, groups="base.group_system")
    has_secret = fields.Boolean(compute="_compute_has_secret")
    user_id = fields.Many2one(
        "res.users",
        string="Run As User",
        required=True,
        ondelete="restrict",
        help="Technical user the API requests run as. Give it only the access it needs.",
    )
    token_ttl_minutes = fields.Integer(string="Token Lifetime (min)", default=15)
    scope_leads_read = fields.Boolean(string="Read leads", default=True)
    scope_leads_write = fields.Boolean(string="Create leads")
    last_token_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ("client_id_unique", "unique(client_id)", "Client ID must be unique."),
    ]

    @api.depends("secret_hash")
    def _compute_has_secret(self):
        for client in self.sudo():
            client.has_secret = bool(client.secret_hash)

    @api.constrains("token_ttl_minutes")
    def _check_token_ttl(self):
        for client in self:
            if not 1 <= client.token_ttl_minutes <= 1440:
                raise ValidationError(_("Token lifetime must be between 1 and 1440 minutes."))

    def get_scopes(self):
        self.ensure_one()
        scopes = []
        if self.scope_leads_read:
            scopes.append("leads:read")
        if self.scope_leads_write:
            scopes.append("leads:write")
        return scopes

    def check_secret(self, secret):
        self.ensure_one()
        return verify_secret(secret, self.sudo().secret_hash)

    def action_generate_secret(self):
        """Rotate the secret. The plain value is shown once and never stored."""
        self.ensure_one()
        plain = secrets.token_urlsafe(32)
        self.sudo().secret_hash = hash_secret(plain)
        wizard = self.env["rest.api.client.secret"].create({"api_client_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("New Client Secret"),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            # The plain secret only travels in the action context: it is never
            # written to the database, not even in the transient wizard table.
            "context": {"rest_api_plain_secret": plain},
        }
