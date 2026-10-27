"""Stats > Visual chat workflow: which view admins see, "simple" (the original vertical diagram) or "new" (the
inference chart with the app steps as cards). One value for everyone, picked by an admin on the view itself.
"""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting

KEY = "stats_workflow_view"
DEFAULT = "new"
WorkflowViewName = Literal["simple", "new"]


async def get_workflow_view(db: AsyncSession) -> WorkflowViewName:
    row = await db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
    view = row.value.get("view") if row is not None else None
    return view if view in ("simple", "new") else DEFAULT


async def set_workflow_view(db: AsyncSession, view: WorkflowViewName) -> None:
    row = await db.get(AppSetting, (SYSTEM_OWNER_ID, KEY))
    if row is None:
        db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=KEY, value={"view": view}))
    else:
        row.value = {"view": view}
    await db.commit()
