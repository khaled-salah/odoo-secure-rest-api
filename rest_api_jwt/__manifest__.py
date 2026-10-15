{
    "name": "Secure REST API (JWT + Pydantic v2)",
    "summary": "Production-style REST API layer for Odoo: JWT client credentials, "
    "Pydantic v2 validation, per-client access rights and savepoint-based batch writes",
    "version": "17.0.1.0.0",
    "category": "Technical",
    "author": "Khaled Bassiouni Salah",
    "website": "https://github.com/khaled-salah/odoo-secure-rest-api",
    "license": "LGPL-3",
    "depends": ["crm"],
    "external_dependencies": {"python": ["pydantic", "jwt", "email_validator"]},
    "data": [
        "security/ir.model.access.csv",
        "wizard/api_client_secret_views.xml",
        "views/api_client_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
