"""Cluster > Matricxon > Update nodes: "Update all nodes" (services/matricxon_rollout.py)."""

from pydantic import BaseModel, Field

from app.schemas.servers import RolloutOut


class RolloutNode(BaseModel):
    """One node in the rollout, in the fields settings_servers_rollout.js reads for a pAIring server."""

    server_id: str  # the node's address
    leader: bool = False
    update_state: str | None = None  # updating, restarting or rejoining, while it is the current node
    update_progress: dict | None = None  # {step, total_steps, label, percent} while updating


class MatricxonRolloutOverview(BaseModel):
    rollout: RolloutOut | None = None
    servers: list[RolloutNode] = Field(default_factory=list)
    server_time: int


class NodeVersion(BaseModel):
    host: str
    reachable: bool
    version: str | None = None
    commit: str | None = None
    leader: bool = False
    error: str | None = None
