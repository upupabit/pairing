"""The Matricxon API key: Settings > Inference engines (one server or a few), and the Cluster page in cluster mode
(logic: app.services.matricxon_api_key)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import MatricxonApiKeyState, MatricxonApiKeyUpdate
from app.services.auth_service import require_admin
from app.services.cluster_errors import NodeNotAllowedError
from app.services.matricxon_api_key import ApiKeyOnClusterPageError, MatricxonApiKey

router = APIRouter(tags=["matricxon"])


async def _set(db: AsyncSession, key: str, from_cluster_page: bool) -> MatricxonApiKeyState:
    try:
        return await MatricxonApiKey(db).set(key.strip(), from_cluster_page)
    except ApiKeyOnClusterPageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NodeNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/settings/matricxon/api-key", response_model=MatricxonApiKeyState)
async def get_api_key(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonApiKeyState:
    return await MatricxonApiKey(db).state()


@router.put("/api/settings/matricxon/api-key", response_model=MatricxonApiKeyState)
async def set_api_key(
    body: MatricxonApiKeyUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonApiKeyState:
    return await _set(db, body.key, from_cluster_page=False)


@router.put("/api/cluster/api-key", response_model=MatricxonApiKeyState)
async def set_cluster_api_key(
    body: MatricxonApiKeyUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonApiKeyState:
    """Cluster page: the key on every node at once (all must answer)."""
    return await _set(db, body.key, from_cluster_page=True)
