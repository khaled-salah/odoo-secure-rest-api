import secrets

JWT_SECRET_PARAM = "rest_api_jwt.signing_key"  # noqa: S105 (parameter name, not a secret)


def post_init_hook(env):
    """Generate a random JWT signing key on install.

    The key lives in ir.config_parameter (admin-only) and is never hardcoded,
    so every database gets its own key.
    """
    params = env["ir.config_parameter"].sudo()
    if not params.get_param(JWT_SECRET_PARAM):
        params.set_param(JWT_SECRET_PARAM, secrets.token_urlsafe(64))
