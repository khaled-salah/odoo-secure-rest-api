import logging

import psycopg2
import pydantic
from pydantic import BaseModel, ConfigDict, Field

from odoo import exceptions, http
from odoo.http import request

from ..schemas import LeadBatchRequest, LeadCreate, LeadOut
from .base import ApiError, api_endpoint, json_response, pydantic_details, read_json_body

_logger = logging.getLogger(__name__)


class LeadListQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


def _find_by_ref(env, external_ref):
    return env["crm.lead"].search([("rest_api_external_ref", "=", external_ref)], limit=1)


def _create_lead(env, data):
    """Create one lead inside its own savepoint.

    Returns (lead, created). If the external_ref already exists (including a
    concurrent request winning the race on the unique index) the existing lead
    is returned instead, so retries are safe.
    """
    existing = _find_by_ref(env, data.external_ref)
    if existing:
        return existing, False
    try:
        with env.cr.savepoint():
            lead = env["crm.lead"].create(data.to_odoo_vals())
    except psycopg2.errors.UniqueViolation as exc:
        existing = _find_by_ref(env, data.external_ref)
        if not existing:  # exists but hidden from this user by record rules
            raise ApiError(
                409, "conflict", "A lead with this external_ref already exists."
            ) from exc
        return existing, False
    return lead, True


class RestApiLeadController(http.Controller):
    @http.route(
        "/api/v1/leads", type="http", auth="public", methods=["GET"], csrf=False, save_session=False
    )
    @api_endpoint(scope="leads:read")
    def list_leads(self, **params):
        query = LeadListQuery.model_validate(params)
        Lead = request.env["crm.lead"]
        domain = [("type", "=", "lead")]
        leads = Lead.search(domain, limit=query.limit, offset=query.offset, order="id desc")
        return json_response(
            {
                "data": [LeadOut.from_record(lead).model_dump() for lead in leads],
                "meta": {
                    "limit": query.limit,
                    "offset": query.offset,
                    "total": Lead.search_count(domain),
                },
            }
        )

    @http.route(
        "/api/v1/leads/<int:lead_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @api_endpoint(scope="leads:read")
    def get_lead(self, lead_id, **_kwargs):
        lead = request.env["crm.lead"].browse(lead_id).exists()
        if not lead:
            raise ApiError(404, "not_found", "Lead not found.")
        lead.check_access_rule("read")
        return json_response({"data": LeadOut.from_record(lead).model_dump()})

    @http.route(
        "/api/v1/leads",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @api_endpoint(scope="leads:write")
    def create_lead(self, **_kwargs):
        data = LeadCreate.model_validate(read_json_body())
        lead, created = _create_lead(request.env, data)
        return json_response(
            {"data": LeadOut.from_record(lead).model_dump(), "created": created},
            status=201 if created else 200,
        )

    @http.route(
        "/api/v1/leads/batch",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @api_endpoint(scope="leads:write")
    def create_leads_batch(self, **_kwargs):
        """Partial persistence: every valid item is saved, every bad item is reported.

        Each item runs in its own savepoint, so one failing lead rolls back only
        its own writes and never poisons the rest of the transaction.
        """
        batch = LeadBatchRequest.model_validate(read_json_body())
        results = []
        for index, item in enumerate(batch.leads):
            try:
                data = LeadCreate.model_validate(item)
                lead, created = _create_lead(request.env, data)
            except pydantic.ValidationError as exc:
                results.append(
                    {"index": index, "status": "invalid", "errors": pydantic_details(exc)}
                )
            except ApiError as exc:
                results.append({"index": index, "status": "error", "error": exc.message})
            except (exceptions.UserError, exceptions.ValidationError) as exc:
                results.append({"index": index, "status": "error", "error": str(exc)})
            else:
                results.append(
                    {
                        "index": index,
                        "status": "created" if created else "existing",
                        "id": lead.id,
                    }
                )

        succeeded = sum(r["status"] in ("created", "existing") for r in results)
        return json_response(
            {
                "results": results,
                "summary": {
                    "total": len(results),
                    "succeeded": succeeded,
                    "failed": len(results) - succeeded,
                },
            },
            status=207 if succeeded != len(results) else 200,
        )
