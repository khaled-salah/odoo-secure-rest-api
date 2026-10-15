from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    grant_type: Literal["client_credentials"] = "client_credentials"
    client_id: str = Field(min_length=1, max_length=128)
    client_secret: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    scope: str
