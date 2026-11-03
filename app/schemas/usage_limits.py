"""Daily usage limits per user (services/usage_limits.py). 0 means no limit."""

from pydantic import BaseModel, Field


class UsageLimits(BaseModel):
    replies_per_day: int = Field(0, ge=0, le=1_000_000)
    tokens_per_day: int = Field(0, ge=0, le=1_000_000_000)


class UserUsageLimits(BaseModel):
    """A user's own limits; None uses the default."""

    replies_per_day: int | None = Field(None, ge=0, le=1_000_000)
    tokens_per_day: int | None = Field(None, ge=0, le=1_000_000_000)


class UserUsageOut(BaseModel):
    """A user's override, what applies, and the last 24 hours' use."""

    override: UserUsageLimits
    effective: UsageLimits
    replies_used: int
    tokens_used: int
    exempt: bool  # admins have no limits
