from sqlalchemy import Column, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Action(Base):
    __tablename__ = "actions"

    id = Column(Text, primary_key=True)
    entity_id = Column(Text, nullable=False, index=True)
    entity_type = Column(Text, nullable=False)
    entity_name = Column(Text, nullable=False)
    namespace = Column(Text, nullable=False)
    action_type = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False, index=True)
    user_team = Column(Text, nullable=True)
    parameters = Column(JSONB, default=dict)
    reason = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending", index=True)
    result_message = Column(Text, nullable=True)
    correlation_id = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Text, primary_key=True)
    entity_id = Column(Text, nullable=False, unique=True)
    entity_name = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    health_state = Column(Text, nullable=False)
    reason = Column(Text, nullable=True)
    root_cause_entity_id = Column(Text, nullable=True)
    root_cause_entity_name = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=False)
    owner_team = Column(Text, nullable=True)
    tier = Column(Text, nullable=True)
    event_id = Column(Text, nullable=False)
    since = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
