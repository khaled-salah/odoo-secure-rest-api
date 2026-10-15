import json
from datetime import datetime, timedelta, timezone

import jwt

from odoo.tests import HttpCase, new_test_user, tagged

from ..hooks import JWT_SECRET_PARAM
from ..models.api_client import hash_secret
from ..services.tokens import AUDIENCE

SECRET = "test-client-secret"


@tagged("post_install", "-at_install", "rest_api")
class TestRestApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env, login="api_bot", groups="sales_team.group_sale_salesman_all_leads"
        )
        cls.client = cls.env["rest.api.client"].create(
            {
                "name": "Test Integration",
                "user_id": cls.api_user.id,
                "scope_leads_read": True,
                "scope_leads_write": True,
            }
        )
        cls.client.sudo().secret_hash = hash_secret(SECRET)

    # -- helpers ---------------------------------------------------------
    def _post(self, path, payload, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.url_open(path, data=json.dumps(payload), headers=headers)

    def _get(self, path, token):
        return self.url_open(path, headers={"Authorization": f"Bearer {token}"})

    def _token(self, secret=SECRET):
        return self._post(
            "/api/v1/auth/token",
            {"client_id": self.client.client_id, "client_secret": secret},
        )

    def _access_token(self):
        response = self._token()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def _lead_payload(self, ref="ORD-100", **overrides):
        payload = {"external_ref": ref, "name": "Merchant signup", "email": "m@example.com"}
        payload.update(overrides)
        return payload

    # -- authentication --------------------------------------------------
    def test_token_issued_with_scopes(self):
        body = self._token().json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(set(body["scope"].split()), {"leads:read", "leads:write"})
        self.assertEqual(body["expires_in"], 15 * 60)

    def test_wrong_secret_and_unknown_client_look_identical(self):
        wrong = self._token(secret="nope")
        unknown = self._post("/api/v1/auth/token", {"client_id": "x", "client_secret": "y"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())

    def test_missing_expired_and_forged_tokens_rejected(self):
        self.assertEqual(self._get("/api/v1/leads", token="").status_code, 401)

        key = self.env["ir.config_parameter"].sudo().get_param(JWT_SECRET_PARAM)
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        claims = {
            "sub": self.client.client_id,
            "aud": AUDIENCE,
            "iss": self.env.cr.dbname,
            "scope": "leads:read",
            "iat": past,
            "exp": past + timedelta(minutes=5),
        }
        expired = jwt.encode(claims, key, algorithm="HS256")
        response = self._get("/api/v1/leads", expired)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "token expired")

        claims["exp"] = datetime.now(timezone.utc) + timedelta(minutes=5)
        forged = jwt.encode(
            claims, "an-attacker-guessed-key-that-is-long-enough", algorithm="HS256"
        )
        self.assertEqual(self._get("/api/v1/leads", forged).status_code, 401)

    def test_archiving_client_revokes_live_tokens(self):
        token = self._access_token()
        self.client.active = False
        self.assertEqual(self._get("/api/v1/leads", token).status_code, 401)

    def test_scope_removed_after_issuance_is_enforced(self):
        token = self._access_token()
        self.client.scope_leads_write = False
        response = self._post("/api/v1/leads", self._lead_payload(), token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    # -- leads -----------------------------------------------------------
    def test_create_lead_runs_as_api_user_and_is_idempotent(self):
        token = self._access_token()
        first = self._post("/api/v1/leads", self._lead_payload(expected_revenue=500), token)
        self.assertEqual(first.status_code, 201, first.text)
        lead = self.env["crm.lead"].browse(first.json()["data"]["id"])
        self.assertEqual(lead.create_uid, self.api_user, "API must not run as superuser")
        self.assertEqual(lead.expected_revenue, 500)

        again = self._post("/api/v1/leads", self._lead_payload(), token)
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["created"])
        self.assertEqual(again.json()["data"]["id"], lead.id)

    def test_validation_errors_do_not_echo_input(self):
        token = self._access_token()
        response = self._post(
            "/api/v1/leads", self._lead_payload(email="bad", password="hunter2"), token
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("hunter2", response.text)
        locs = {tuple(d["loc"]) for d in response.json()["error"]["details"]}
        self.assertIn(("email",), locs)
        self.assertIn(("password",), locs)

    def test_batch_partial_persistence(self):
        token = self._access_token()
        payload = {
            "leads": [
                self._lead_payload("B-1"),
                self._lead_payload("B-2", email=None),  # invalid: no contact channel
                self._lead_payload("B-3", phone="+20 100 000 0000"),
                self._lead_payload("B-1"),  # duplicate in same batch -> existing
            ]
        }
        response = self._post("/api/v1/leads/batch", payload, token)
        self.assertEqual(response.status_code, 207, response.text)
        body = response.json()
        self.assertEqual(
            [r["status"] for r in body["results"]], ["created", "invalid", "created", "existing"]
        )
        self.assertEqual(body["summary"], {"total": 4, "succeeded": 3, "failed": 1})
        refs = (
            self.env["crm.lead"]
            .search([("rest_api_external_ref", "like", "B-")])
            .mapped("rest_api_external_ref")
        )
        self.assertCountEqual(refs, ["B-1", "B-3"])

    def test_read_endpoints(self):
        token = self._access_token()
        created = self._post("/api/v1/leads", self._lead_payload("R-1"), token).json()
        lead_id = created["data"]["id"]

        one = self._get(f"/api/v1/leads/{lead_id}", token)
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.json()["data"]["external_ref"], "R-1")

        self.assertEqual(self._get("/api/v1/leads/999999999", token).status_code, 404)
        page = self._get("/api/v1/leads?limit=1", token).json()
        self.assertEqual(len(page["data"]), 1)
        self.assertGreaterEqual(page["meta"]["total"], 1)
        self.assertEqual(self._get("/api/v1/leads?limit=1000", token).status_code, 422)

    def test_invalid_json_body(self):
        token = self._access_token()
        response = self.url_open(
            "/api/v1/leads",
            data="{not json",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_json")
