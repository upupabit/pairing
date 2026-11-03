"""Daily usage limits per user: AI replies and generated tokens in the last 24 hours (Admin settings > Users).

A default for everyone plus an optional per-user override, both stored as app settings. 0 means no limit.
Admins are never limited. Tokens come from each reply's stats (reply_stats.py), so only engines that report
counts (llama.cpp, Matricxon) add to them. Checked before a reply starts (routers/chat.py).
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import SYSTEM_OWNER_ID, AppSetting, Message, User
from app.models._base import utcnow
from app.schemas.usage_limits import UsageLimits, UserUsageLimits, UserUsageOut

KEY = "usage_limits"
WINDOW = timedelta(hours=24)


class UsageLimitService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def defaults(self) -> UsageLimits:
        return UsageLimits(**await self._read(SYSTEM_OWNER_ID))

    async def set_defaults(self, limits: UsageLimits) -> UsageLimits:
        await self._write(SYSTEM_OWNER_ID, limits.model_dump())
        return limits

    async def for_user(self, user: User) -> UserUsageOut:
        override = UserUsageLimits(**await self._read(user.id))
        replies, tokens = await self.used(user.id)
        return UserUsageOut(
            override=override,
            effective=await self._effective(override),
            replies_used=replies,
            tokens_used=tokens,
            exempt=user.role == "admin",
        )

    async def set_for_user(self, user: User, override: UserUsageLimits) -> UserUsageOut:
        await self._write(user.id, override.model_dump())
        return await self.for_user(user)

    async def used(self, user_id: str) -> tuple[int, int]:
        """Replies (any outcome) to this user's messages in the last 24 hours, and their generated tokens."""
        asked = aliased(Message)
        rows = await self._db.execute(
            select(Message.stats)
            .join(asked, Message.reply_to_message_id == asked.id)
            .where(Message.role == "assistant", asked.sender_id == user_id, Message.created_at > utcnow() - WINDOW)
        )
        stats = [row for (row,) in rows]
        return len(stats), sum(int((s or {}).get("output_tokens") or 0) for s in stats)

    async def check(self, user: User) -> None:
        """429 when a new reply would go over this user's limits."""
        usage = await self.for_user(user)
        if usage.exempt:
            return
        limits = usage.effective
        if limits.replies_per_day and usage.replies_used >= limits.replies_per_day:
            raise HTTPException(status_code=429, detail=self._message(f"{limits.replies_per_day} AI replies"))
        if limits.tokens_per_day and usage.tokens_used >= limits.tokens_per_day:
            raise HTTPException(status_code=429, detail=self._message(f"{limits.tokens_per_day:,} generated tokens"))

    async def _effective(self, override: UserUsageLimits) -> UsageLimits:
        base = await self.defaults()
        return UsageLimits(
            replies_per_day=base.replies_per_day if override.replies_per_day is None else override.replies_per_day,
            tokens_per_day=base.tokens_per_day if override.tokens_per_day is None else override.tokens_per_day,
        )

    @staticmethod
    def _message(limit: str) -> str:
        return f"You reached your limit of {limit} in 24 hours. Please try again later, or ask an admin."

    async def _read(self, owner_id: str) -> dict:
        row = await self._db.get(AppSetting, (owner_id, KEY))
        return dict(row.value) if row and isinstance(row.value, dict) else {}

    async def _write(self, owner_id: str, value: dict) -> None:
        row = await self._db.get(AppSetting, (owner_id, KEY))
        if row is None:
            self._db.add(AppSetting(owner_id=owner_id, key=KEY, value=value))
        else:
            row.value = value
        await self._db.commit()
