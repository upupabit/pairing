"""In-memory index of the knowledge base's chunk vectors for RAG search (document_retrieval.retrieve_context).

All vectors sit in one normalized float32 matrix per vector size, so a question is one matrix-vector product instead
of loading every chunk from the database and comparing them one by one. Each search first reads a cheap signature
(documents' ids, owners and embedding models, plus every chunk id: a re-embed with the same model rewrites the chunks
under new ids and changes nothing else); the index rebuilds only when it changed, so uploads, deletes, re-embeds and
other instances' changes are all picked up. ROADMAP.md: a real vector index
(e.g. sqlite-vec) for much larger stores.
"""

import asyncio
import hashlib
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document


@dataclass
class _Block:
    """Every chunk with one vector size: unit-length rows plus who may see each and which model made it."""

    vectors: np.ndarray  # (n, dim) float32, rows normalized
    chunk_ids: np.ndarray  # (n,) object
    owners: np.ndarray  # (n,) object, None = shared
    models: np.ndarray  # (n,) object, None = not recorded


class ChunkVectorIndex:
    def __init__(self) -> None:
        self._signature: str | None = None
        self._blocks: dict[int, _Block] = {}
        self._lock = asyncio.Lock()

    async def search(
        self,
        db: AsyncSession,
        query_vector: np.ndarray,
        user_id: str | None,
        model: str,
        limit: int,
        refresh: bool = True,
    ) -> list[str]:
        """Ids of the `limit` chunks most similar to `query_vector` (cosine), best first: chunks `user_id` may see
        (None = shared only), embedded with `model` (or unrecorded) and of the same vector size. `refresh=False`
        skips the change check when the caller just ran it (has_visible)."""
        if refresh:
            await self.refresh(db)
        block = self._blocks.get(query_vector.shape[0])
        if block is None or limit <= 0:
            return []
        allowed = self._visible(block, user_id) & ((block.models == model) | (block.models == None))  # noqa: E711
        if not allowed.any():
            return []
        query = query_vector.astype(np.float32) / (np.linalg.norm(query_vector) or 1.0)
        scores = np.where(allowed, block.vectors @ query, -np.inf)
        count = min(limit, int(allowed.sum()))
        best = np.argpartition(-scores, count - 1)[:count]
        best = best[np.argsort(-scores[best], kind="stable")]
        return [str(chunk_id) for chunk_id in block.chunk_ids[best]]

    async def has_visible(self, db: AsyncSession, user_id: str | None) -> bool:
        """Whether `user_id` can see any chunk at all (lets retrieval skip embedding the question)."""
        await self.refresh(db)
        return any(self._visible(block, user_id).any() for block in self._blocks.values())

    async def refresh(self, db: AsyncSession) -> None:
        signature = await self._read_signature(db)
        if signature == self._signature:
            return
        async with self._lock:
            if signature != self._signature:
                self._blocks = await self._build(db)
                self._signature = signature

    @staticmethod
    def _visible(block: _Block, user_id: str | None) -> np.ndarray:
        shared = block.owners == None  # noqa: E711 - elementwise on an object array
        return shared if user_id is None else shared | (block.owners == user_id)

    @staticmethod
    async def _read_signature(db: AsyncSession) -> str:
        documents = await db.execute(
            select(Document.id, Document.owner_id, Document.embedding_model).order_by(Document.id)
        )
        digest = hashlib.sha256()
        for row in documents:
            digest.update("|".join(str(value) for value in row).encode())
        chunk_ids = (await db.execute(select(Chunk.id).order_by(Chunk.id))).scalars()
        digest.update(",".join(chunk_ids).encode())
        return digest.hexdigest()

    @staticmethod
    async def _build(db: AsyncSession) -> dict[int, _Block]:
        rows = await db.execute(
            select(Chunk.id, Chunk.embedding, Document.owner_id, Document.embedding_model).join(Document)
        )
        grouped: dict[int, list[tuple]] = {}
        for chunk_id, embedding, owner, model in rows:
            vector = np.frombuffer(embedding, dtype=np.float32)
            grouped.setdefault(vector.shape[0], []).append((chunk_id, vector, owner, model))
        blocks = {}
        for dim, items in grouped.items():
            vectors = np.stack([item[1] for item in items]).astype(np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors /= np.where(norms == 0, 1.0, norms)
            blocks[dim] = _Block(
                vectors=vectors,
                chunk_ids=np.array([item[0] for item in items], dtype=object),
                owners=np.array([item[2] for item in items], dtype=object),
                models=np.array([item[3] for item in items], dtype=object),
            )
        return blocks


chunk_vector_index = ChunkVectorIndex()
