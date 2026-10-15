from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    rest_api_external_ref = fields.Char(
        string="External Reference",
        copy=False,
        index=True,
        help="Reference sent by the external system. Makes lead creation idempotent.",
    )

    _sql_constraints = [
        (
            "rest_api_external_ref_unique",
            "unique(rest_api_external_ref)",
            "A lead with this external reference already exists.",
        ),
    ]
