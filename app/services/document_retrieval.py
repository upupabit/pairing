"""The read side of RAG: turns a question into the most relevant stored chunks (written by document_ingest.py)."""

from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RAG_TOP_K
from app.models import Chunk
from app.services import model_catalog_service
from app.services.chunk_vector_index import chunk_vector_index
from app.services.default_model_settings import DefaultModelSettings
from app.services.document_rerank import ChunkReranker
from app.services.inference_client import embed
from app.services.live_workflow_bus import live_workflow


async def retrieve_context(
    db: AsyncSession,
    query: str,
    user_id: str | None,
    top_k: int = RAG_TOP_K,
) -> list[dict]:
    """Embeds `query` and returns the top_k most similar chunks `user_id` may see, best first. `user_id` set =
    personal chat: own private documents plus shared "global" ones. `user_id=None` = channel chat
    (Conversation.channel_id): global only, so one member's private uploads are never exposed to the channel
    (chat_service.py call site). Each result has the chunk text and its document's display name (not the
    owner-scoped path), to build the prompt (build_augmented_system_prompt) and show sources. Empty list if
    nothing exists in scope.
    """
    async with live_workflow.stage("rag_retrieve"):
        return await _retrieve(db, query, user_id, top_k)


async def _retrieve(db: AsyncSession, query: str, user_id: str | None, top_k: int) -> list[dict]:
    if not await chunk_vector_index.has_visible(db, user_id):
        return []

    embedding_model = await model_catalog_service.get_default_embedding_model(db)
    if embedding_model is None:
        # No embedding model installed (or the chunks' model was uninstalled): degrade as document_sync does, no hard
        # failure.
        return []

    async with live_workflow.stage("rag_embed", "rag_embed_ml_engine"):
        query_vector = np.asarray(await embed(query, embedding_model), dtype=np.float32)

    # Cosine similarity over the in-memory index. Only vectors from the current model compare: another model's
    # (recorded, or of another size when unknown) waits for the next sync to re-embed it instead of matching badly.
    # A reranker, if set, gets a wider shortlist (Settings > System > Reranker: passages to rerank).
    shortlist = max(top_k, await DefaultModelSettings(db).rerank_candidates())
    async with live_workflow.stage("rag_rank"):
        ids = await chunk_vector_index.search(db, query_vector, user_id, embedding_model, shortlist, refresh=False)
        by_id = {c.id: c for c in (await db.execute(select(Chunk).where(Chunk.id.in_(ids)))).scalars()}
    # A reranker, if set, picks the best top_k from a wider similarity shortlist.
    candidates = [by_id[chunk_id] for chunk_id in ids if chunk_id in by_id]
    best = await ChunkReranker(db).order(query, candidates, top_k)
    # chunk.document is selectin-loaded (models/document.py), so access is safe under the async session.
    return [
        {"text": chunk.text, "filename": Path(chunk.document.filename).name, "document_id": chunk.document_id}
        for chunk in best
    ]


def build_augmented_system_prompt(base_prompt: str, retrieved_chunks: list[dict]) -> str:
    """Appends retrieved excerpts to the system prompt, labeled so the model tells background material from
    instructions."""
    if not retrieved_chunks:
        return base_prompt
    context_block = "\n\n---\n\n".join(chunk["text"] for chunk in retrieved_chunks)
    return (
        f"{base_prompt}\n\n"
        "Use the following reference material to answer the user's next "
        "question if it's relevant. If it isn't relevant, ignore it and "
        "answer normally. Do not mention that you were given reference "
        "material.\n\n"
        f"### Reference material\n{context_block}"
    )


def build_attachment_system_prompt(base_prompt: str, filename: str, text: str) -> str:
    """Like build_augmented_system_prompt, for one ad-hoc file attached to this message
    (chat_attachment_service, chat_service.build_reply_stream); labeled by filename since there's only one.
    """
    return (
        f"{base_prompt}\n\n"
        f'The user has attached a file named "{filename}" with this message. '
        "Use its content to answer if relevant.\n\n"
        f"### Attached file: {filename}\n{text}"
    )
