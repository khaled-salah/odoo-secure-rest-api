import pydantic

from odoo.tests import BaseCase, tagged

from ..models.api_client import hash_secret, verify_secret
from ..schemas import LeadCreate


@tagged("post_install", "-at_install", "rest_api")
class TestSchemas(BaseCase):
    def _lead(self, **overrides):
        data = {"external_ref": "ORD-1", "name": "Website lead", "email": "a@example.com"}
        data.update(overrides)
        return LeadCreate.model_validate(data)

    def test_valid_lead_maps_to_odoo_vals(self):
        vals = self._lead(expected_revenue=150).to_odoo_vals()
        self.assertEqual(vals["email_from"], "a@example.com")
        self.assertEqual(vals["rest_api_external_ref"], "ORD-1")
        self.assertEqual(vals["type"], "lead")

    def test_requires_email_or_phone(self):
        with self.assertRaises(pydantic.ValidationError):
            self._lead(email=None)
        self.assertEqual(self._lead(email=None, phone="+966 55 123 4567").phone, "+966 55 123 4567")

    def test_rejects_unknown_fields_and_bad_values(self):
        for bad in (
            {"is_admin": True},
            {"expected_revenue": -1},
            {"email": "nope"},
            {"external_ref": "has space"},
        ):
            with self.subTest(bad=bad), self.assertRaises(pydantic.ValidationError):
                self._lead(**bad)

    def test_secret_hashing(self):
        stored = hash_secret("s3cret")
        self.assertNotIn("s3cret", stored)
        self.assertTrue(verify_secret("s3cret", stored))
        self.assertFalse(verify_secret("wrong", stored))
        self.assertFalse(verify_secret("s3cret", "garbage"))
