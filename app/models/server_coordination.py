"""Rows that let several pAIring servers share one database: the leader lease, upload jobs and the server list."""

from sqlalchemy import JSON, BigInteger, Boolean, Column, String, Text

from app.database import Base
from app.models._base import ID_LEN, Timestamp, utcnow


class LeaderLease(Base):
    """One row per lease ("leader"): who holds it and until when, in database epoch seconds
    (services/leader_lease.py). Seeded by its migration."""

    __tablename__ = "leader_leases"

    name = Column(String(64), primary_key=True)
    holder = Column(String(255), nullable=True)
    expires_at = Column(BigInteger, nullable=False, default=0)


class UploadJob(Base):
    """A knowledge-base upload's progress (services/upload_jobs.py), readable by every server."""

    __tablename__ = "upload_jobs"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(ID_LEN), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    files = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    created_at = Column(Timestamp, nullable=False, default=utcnow)
    # config.SERVER_ID of the server running it; set with `error` when that server restarts or goes offline.
    owner_server = Column(String(255), nullable=True)
    error = Column(Text, nullable=True)


class Server(Base):
    """One row per pAIring process, kept fresh by its heartbeat (services/server_registry.py). `last_seen` is
    database epoch seconds. `update_round`/`update_state` are its part in an "Update all" (rolling_update.py)."""

    __tablename__ = "servers"

    server_id = Column(String(255), primary_key=True)
    version = Column(String(32), nullable=False)
    git_commit = Column(String(40), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=True)
    started_at = Column(Timestamp, nullable=False, default=utcnow)
    last_seen = Column(BigInteger, nullable=False, default=0)
    update_round = Column(String(64), nullable=True)
    update_state = Column(Text, nullable=True)
    # What the multi-server checks compare (servers_check.py): SECRET_KEY fingerprint, the shared folders.
    details = Column(JSON, nullable=True)
