"""
Embedding client using BAAI/bge-m3 via OpenRouter.
No local model needed — calls the OpenAI-compatible embeddings endpoint.
"""

import logging
from typing import Union

import httpx
from config import get_settings

logger = logging.getLogger("devops_agent.memory.embedder")

# OpenAI text-embedding-3-small (native)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1024


async def embed_text(text: str) -> list[float]:
    """
    Generate a 1024-dim embedding for a single text string
    using text-embedding-3-small.
    """
    settings = get_settings()

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for embeddings")

    # OpenAI native /v1/embeddings endpoint
    url = "https://api.openai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": text[:8000],  # chunk to stay under context limits safely
        "dimensions": EMBEDDING_DIMENSIONS,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(
                "Embedding API error %d: %s",
                resp.status_code,
                resp.text[:500],
            )
            raise RuntimeError(f"Embedding API returned {resp.status_code}")

        data = resp.json()

    # OpenAI-compatible format: { data: [{ embedding: [...] }] }
    embedding = data["data"][0]["embedding"]

    # Validate dimensions
    if len(embedding) != EMBEDDING_DIMENSIONS:
        logger.warning(
            "Expected %d dimensions, got %d — truncating/padding",
            EMBEDDING_DIMENSIONS,
            len(embedding),
        )
        embedding = embedding[:EMBEDDING_DIMENSIONS]
        while len(embedding) < EMBEDDING_DIMENSIONS:
            embedding.append(0.0)

    return embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Batch embed multiple texts. Calls the API once per text.
    For high-volume use, consider batching at the API level.
    """
    results = []
    for text in texts:
        emb = await embed_text(text)
        results.append(emb)
    return results
