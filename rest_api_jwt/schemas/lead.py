import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

PHONE_RE = re.compile(r"^\+?[0-9 ()-]{6,20}$")

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=255)]


class LeadCreate(BaseModel):
    """Payload for creating one CRM lead.

    `external_ref` makes the endpoint idempotent: sending the same reference
    twice returns the existing lead instead of creating a duplicate.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_ref: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]
    name: NonEmptyStr
    contact_name: NonEmptyStr | None = None
    email: EmailStr | None = None
    phone: str | None = None
    expected_revenue: Annotated[float, Field(ge=0)] = 0.0
    description: Annotated[str, Field(max_length=5000)] | None = None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value):
        if value is not None and not PHONE_RE.match(value):
            raise ValueError("invalid phone number")
        return value

    @model_validator(mode="after")
    def _require_a_contact_channel(self):
        if not (self.email or self.phone):
            raise ValueError("either email or phone is required")
        return self

    def to_odoo_vals(self):
        return {
            "name": self.name,
            "contact_name": self.contact_name,
            "email_from": self.email,
            "phone": self.phone,
            "expected_revenue": self.expected_revenue,
            "description": self.description,
            "rest_api_external_ref": self.external_ref,
            "type": "lead",
        }


class LeadBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leads: Annotated[list[dict], Field(min_length=1, max_length=100)]


class LeadOut(BaseModel):
    id: int
    external_ref: str | None
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    expected_revenue: float
    stage: str | None

    @classmethod
    def from_record(cls, lead):
        return cls(
            id=lead.id,
            external_ref=lead.rest_api_external_ref or None,
            name=lead.name,
            contact_name=lead.contact_name or None,
            email=lead.email_from or None,
            phone=lead.phone or None,
            expected_revenue=lead.expected_revenue,
            stage=lead.stage_id.name or None,
        )
