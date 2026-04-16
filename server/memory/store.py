"""
Agent episodic memory store — asyncpg CRUD for the agent_memory table.
Uses pgvector for semantic similarity search across all repos (global memory).
"""

import logging
from datetime import datetime, timezone

import asyncpg
from memory.embedder import embed_text, EMBEDDING_DIMENSIONS
from rsi.db import get_pool, init_db

logger = logging.getLogger("devops_agent.memory.store")


async def store_memory(
    repo_id: str,
    error_signature: str,
    error_logs: str,
    root_cause: str,
    fix_summary: str,
    files_changed: list[str],
    pr_url: str = "",
    pr_number: int | None = None,
    language: str = "",
) -> int:
    """
    Store a successful fix experience in the memory bank.
    Generates an embedding of the combined knowledge text and inserts into agent_memory.
    Returns the memory ID.
    """
    await init_db()

    # Build the text to embed — combines the error signature, root cause, and fix summary
    # so semantic search can match on any of these aspects
    knowledge_text = f"{error_signature}\n{root_cause}\n{fix_summary}"
    embedding = await embed_text(knowledge_text)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check for duplicate error_signature (deduplication)
        existing = await conn.fetchrow(
            """
            SELECT id, hit_count FROM agent_memory
            WHERE error_signature = $1 AND repo_id = $2
            """,
            error_signature,
            repo_id,
        )

        if existing:
            # Update existing memory — bump hit_count and refresh timestamps
            memory_id = existing["id"]
            await conn.execute(
                """
                UPDATE agent_memory
                SET hit_count = hit_count + 1,
                    last_hit_at = now(),
                    fix_summary = $1,
                    root_cause = $2,
                    pr_url = $3,
                    merged_at = now(),
                    embedding = $4
                WHERE id = $5
                """,
                fix_summary,
                root_cause,
                pr_url,
                str(embedding),
                memory_id,
            )
            logger.info("Updated existing memory #%d for %s", memory_id, repo_id)
            return memory_id

        # Insert new memory
        memory_id = await conn.fetchval(
            """
            INSERT INTO agent_memory (
                repo_id, error_signature, error_logs, root_cause,
                fix_summary, files_changed, pr_url, pr_number,
                language, embedding
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            repo_id,
            error_signature,
            error_logs[:10000],  # cap stored logs at 10K chars
            root_cause,
            fix_summary,
            files_changed,
            pr_url,
            pr_number,
            language,
            str(embedding),
        )

    logger.info("Stored new memory #%d for %s: %s", memory_id, repo_id, error_signature[:80])
    return memory_id


async def search_memory(
    error_text: str,
    top_k: int = 3,
    threshold: float = 0.60,
) -> list[dict]:
    """
    Search the global memory bank for fix experiences similar to the given error text.
    Uses pgvector cosine similarity (<=> operator).
    Returns the top_k most similar memories above the similarity threshold.
    """
    await init_db()

    embedding = await embed_text(error_text)
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, repo_id, error_signature, root_cause,
                fix_summary, files_changed, pr_url, language,
                merged_at,
                1 - (embedding <=> $1::vector) AS similarity
            FROM agent_memory
            WHERE 1 - (embedding <=> $1::vector) > $2
            ORDER BY embedding <=> $1::vector ASC
            LIMIT $3
            """,
            str(embedding),
            threshold,
            top_k,
        )

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "repo_id": row["repo_id"],
            "error_signature": row["error_signature"],
            "root_cause": row["root_cause"],
            "fix_summary": row["fix_summary"],
            "files_changed": list(row["files_changed"]) if row["files_changed"] else [],
            "pr_url": row["pr_url"],
            "language": row["language"],
            "similarity": round(float(row["similarity"]), 3),
            "merged_at": row["merged_at"].isoformat() if row["merged_at"] else None,
        })

    if results:
        logger.info(
            "Memory recall: found %d matching memories (best similarity: %.3f)",
            len(results),
            results[0]["similarity"],
        )
    else:
        logger.info("Memory recall: no matching memories found above threshold %.2f", threshold)

    # Update hit_count for retrieved memories
    if results:
        memory_ids = [r["id"] for r in results]
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE agent_memory
                SET hit_count = hit_count + 1, last_hit_at = now()
                WHERE id = ANY($1)
                """,
                memory_ids,
            )

    return results


async def get_memory_stats() -> dict:
    """Return high-level memory bank statistics."""
    await init_db()
    pool = await get_pool()

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM agent_memory") or 0
        repos = await conn.fetchval("SELECT COUNT(DISTINCT repo_id) FROM agent_memory") or 0
        most_hit = await conn.fetchrow(
            """
            SELECT error_signature, hit_count, repo_id
            FROM agent_memory 
            ORDER BY hit_count DESC 
            LIMIT 1
            """
        )

    stats = {
        "total_memories": total,
        "repos_with_memories": repos,
        "most_recalled": None,
    }
    if most_hit and most_hit["hit_count"] > 0:
        stats["most_recalled"] = {
            "error_signature": most_hit["error_signature"],
            "hit_count": most_hit["hit_count"],
            "repo": most_hit["repo_id"],
        }

    return stats


async def get_all_memories(limit: int = 50) -> list[dict]:
    """Return all memories, newest first (for the dashboard)."""
    await init_db()
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, repo_id, error_signature, root_cause,
                   fix_summary, files_changed, pr_url, pr_number,
                   language, hit_count, merged_at, created_at
            FROM agent_memory
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "id": r["id"],
            "repo_id": r["repo_id"],
            "error_signature": r["error_signature"],
            "root_cause": r["root_cause"],
            "fix_summary": r["fix_summary"],
            "files_changed": list(r["files_changed"]) if r["files_changed"] else [],
            "pr_url": r["pr_url"],
            "pr_number": r["pr_number"],
            "language": r["language"],
            "hit_count": r["hit_count"],
            "merged_at": r["merged_at"].isoformat() if r["merged_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
