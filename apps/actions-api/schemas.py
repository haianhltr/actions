from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActionRequest(BaseModel):
    entity_id: str
    action_type: str
    user: str
    reason: str | None = None
    parameters: dict = {}


class ActionResponse(BaseModel):
    action_id: str
    status: str
    result_message: str | None = None
    completed_at: datetime | None = None


class ActionDetail(BaseModel):
    id: str
    entity_id: str
    entity_type: str
    entity_name: str
    namespace: str
    action_type: str
    user_id: str
    user_team: str | None = None
    parameters: dict = {}
    reason: str | None = None
    status: str
    result_message: str | None = None
    correlation_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
