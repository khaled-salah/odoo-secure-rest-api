from odoo import fields, models


class RestApiClientSecret(models.TransientModel):
    _name = "rest.api.client.secret"
    _description = "Show a newly generated REST API client secret once"

    api_client_id = fields.Many2one("rest.api.client", required=True, ondelete="cascade")
    client_id = fields.Char(related="api_client_id.client_id")
    client_secret = fields.Char(compute="_compute_client_secret")

    def _compute_client_secret(self):
        plain = self.env.context.get("rest_api_plain_secret", "")
        for wizard in self:
            wizard.client_secret = plain
