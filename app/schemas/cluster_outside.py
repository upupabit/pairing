"""Cluster page > Non-cluster hosts: Matricxon hosts pAIring lists that are not in the running cluster."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import MAX_REMOTE_HOSTS

# Where pAIring keeps a host: the Matricxon it runs, remote hosts, Cluster page nodes, voter list, remembered ids.
HostPlace = Literal["local", "remote", "cluster", "voter", "remembered"]


class OutsideHost(BaseModel):
    host: str
    places: list[HostPlace]
    reachable: bool
    consensus: bool = False  # it runs cluster mode (e.g. still set up for an older cluster)
    managed: bool = False  # the local Matricxon pAIring runs: not removable here


class OutsideHostList(BaseModel):
    cluster: bool  # cluster mode is on
    known: bool  # False: cluster mode is on but no voter answered, so members can't be told apart
    hosts: list[OutsideHost]


class OutsideRemove(BaseModel):
    hosts: list[str] = Field(min_length=1, max_length=4 * MAX_REMOTE_HOSTS)
    reset: bool = False  # also reset the reachable ones to a fresh install


class OutsideReset(BaseModel):
    host: str
    ok: bool
    reason: str = ""


class OutsideRemoveResult(BaseModel):
    removed: list[str]
    resets: list[OutsideReset]
    state: OutsideHostList
