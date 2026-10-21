"""Tests for services/chunk_vector_index.py: the in-memory RAG search index."""

import numpy as np
import pytest
from sqlalchemy import delete

from app.models import Chunk, Document
from app.services.chunk_vector_index import ChunkVectorIndex
from app.services.document_ingest import vector_to_bytes


async def _add(db, name: str, vector: list[float], owner: str | None = None, model: str | None = "emb") -> str:
    document = Document(filename=f"x/{name}", content_hash=name, owner_id=owner, embedding_model=model, chunk_count=1)
    db.add(document)
    await db.flush()
    chunk = Chunk(document_id=document.id, text=name, embedding=vector_to_bytes(np.asarray(vector, dtype=np.float32)))
    db.add(chunk)
    await db.commit()
    return chunk.id


def _q(*values: float) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


@pytest.mark.asyncio
async def test_ranks_by_cosine_best_first(db):
    near = await _add(db, "near", [1.0, 0.1])
    far = await _add(db, "far", [0.0, 1.0])
    mid = await _add(db, "mid", [5.0, 5.0])  # length must not matter

    ids = await ChunkVectorIndex().search(db, _q(1.0, 0.0), None, "emb", 10)

    assert ids == [near, mid, far]


@pytest.mark.asyncio
async def test_limit_keeps_the_best(db):
    best = await _add(db, "best", [1.0, 0.0])
    await _add(db, "worse", [0.0, 1.0])

    assert await ChunkVectorIndex().search(db, _q(1.0, 0.0), None, "emb", 1) == [best]


@pytest.mark.asyncio
async def test_private_chunks_only_for_their_owner(db, user, admin_user):
    shared = await _add(db, "shared", [1.0, 0.0])
    mine = await _add(db, "mine", [1.0, 0.0], owner=user.id)
    theirs = await _add(db, "theirs", [1.0, 0.0], owner=admin_user.id)
    index = ChunkVectorIndex()

    assert set(await index.search(db, _q(1.0, 0.0), user.id, "emb", 10)) == {shared, mine}
    assert await index.search(db, _q(1.0, 0.0), None, "emb", 10) == [shared]  # a channel: shared only
    assert theirs not in await index.search(db, _q(1.0, 0.0), user.id, "emb", 10)


@pytest.mark.asyncio
async def test_other_models_and_sizes_are_skipped(db):
    current = await _add(db, "current", [1.0, 0.0])
    unrecorded = await _add(db, "unrecorded", [0.5, 0.5], model=None)
    await _add(db, "other-model", [1.0, 0.0], model="old")
    await _add(db, "other-size", [1.0, 0.0, 0.0])

    assert await ChunkVectorIndex().search(db, _q(1.0, 0.0), None, "emb", 10) == [current, unrecorded]


@pytest.mark.asyncio
async def test_rebuilds_only_when_documents_change(db, monkeypatch):
    index = ChunkVectorIndex()
    builds = 0
    real_build = ChunkVectorIndex._build

    async def counting_build(session):
        nonlocal builds
        builds += 1
        return await real_build(session)

    monkeypatch.setattr(ChunkVectorIndex, "_build", staticmethod(counting_build))
    first = await _add(db, "first", [1.0, 0.0])
    await index.search(db, _q(1.0, 0.0), None, "emb", 10)
    await index.search(db, _q(1.0, 0.0), None, "emb", 10)
    assert builds == 1

    second = await _add(db, "second", [0.9, 0.1])
    assert await index.search(db, _q(1.0, 0.0), None, "emb", 10) == [first, second]
    await db.execute(delete(Chunk).where(Chunk.id == first))
    await db.commit()
    assert await index.search(db, _q(1.0, 0.0), None, "emb", 10) == [second]
    assert builds == 3


@pytest.mark.asyncio
async def test_has_visible(db, user):
    index = ChunkVectorIndex()
    assert not await index.has_visible(db, user.id)

    await _add(db, "private", [1.0, 0.0], owner=user.id)

    assert await index.has_visible(db, user.id)
    assert not await index.has_visible(db, None)


@pytest.mark.asyncio
async def test_a_re_embed_with_the_same_model_is_picked_up(db):
    """Re-embedding replaces every chunk under a new id; hashes, models and counts stay the same."""
    old = await _add(db, "doc", [1.0, 0.0])
    index = ChunkVectorIndex()
    assert await index.search(db, _q(1.0, 0.0), None, "emb", 10) == [old]
    chunk = await db.get(Chunk, old)
    document_id, embedding = chunk.document_id, chunk.embedding
    await db.execute(delete(Chunk).where(Chunk.id == old))
    db.add(Chunk(document_id=document_id, text="doc", embedding=embedding))
    await db.commit()

    ids = await index.search(db, _q(1.0, 0.0), None, "emb", 10)

    assert len(ids) == 1 and ids != [old]
