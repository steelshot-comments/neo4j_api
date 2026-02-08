from pydantic import BaseModel
from uuid import UUID
from typing import List

class BaseRequest(BaseModel):
    user_id: UUID
    project_id: UUID
    graph_id: UUID

class NodePayload(BaseModel):
    labels: list[str]
    properties: dict[str, str]
    # source_node_id: str

class NodeCreateRequest(BaseRequest):
    nodes: List[NodePayload]

class NodePair(BaseModel):
    from_id: UUID
    to_id: UUID

class RelationshipCreateRequest(BaseRequest):
    pairs: List[NodePair]
    relationship: str

class NodeUpdateRequest(BaseRequest):
    id: UUID
    updates: dict

class NodeDeleteRequest(BaseRequest):
    id: UUID