from datetime import datetime

from pydantic import BaseModel

from app.models.credential import CredentialStatus


class CredentialCreateResponse(BaseModel):
    api_key: str
    secret_key: str
    status: CredentialStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class CredentialListItem(BaseModel):
    api_key: str
    status: CredentialStatus
    created_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}
