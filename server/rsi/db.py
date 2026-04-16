"""
RSI Database CRUD operations using asyncpg.
"""

import logging
import re
from pathlib import Path

import asyncpg
from config import get_settings

logger = logging.getLogger("devops_agent.rsi.db")

_pool: asyncpg.Pool | None = None

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

async def get_pool() -> asyncpg.Pool:
    """Return (and lazily create) the asyncpg connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
        )
        logger.info("Database pool created")
    return _pool

async def init_db() -> None:
    """Run the schema migration (idempotent — uses IF NOT EXISTS)."""
    pool = await get_pool()
    schema_sql = SCHEMA_PATH.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
    logger.info("RSI database schema initialized")

async def close_db() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")

async def insert_rsi_data(
    repo_id: str,
    files: list[dict],
    symbols: list[dict],
    imports: list[dict],
    sensitivities: list[dict]
) -> None:
    """Bulk insert parsed RSI data into the respective tables."""
    if not files:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert file map (includes file_desc + last_indexed_at)
            await conn.executemany(
                """
                INSERT INTO rsi_file_map (repo_id, file_path, role_tag, language, file_sha, line_count, file_desc, last_indexed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (repo_id, file_path) DO UPDATE SET
                    role_tag        = EXCLUDED.role_tag,
                    language        = EXCLUDED.language,
                    file_sha        = EXCLUDED.file_sha,
                    line_count      = EXCLUDED.line_count,
                    file_desc       = EXCLUDED.file_desc,
                    last_indexed_at = now(),
                    created_at      = now()
                """,
                [
                    (repo_id, f["file_path"], f["role_tag"], f["language"],
                     f["file_sha"], f["line_count"], f.get("file_desc", ""))
                    for f in files
                ]
            )

            # Insert symbol map — ON CONFLICT DO NOTHING prevents duplicates
            if symbols:
                await conn.executemany(
                    """
                    INSERT INTO rsi_symbol_map (repo_id, file_path, symbol_name, symbol_type, start_line, end_line, exports)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (repo_id, file_path, symbol_name, symbol_type) DO NOTHING
                    """,
                    [
                        (repo_id, s["file_path"], s["symbol_name"], s["symbol_type"],
                         s["start_line"], s["end_line"], s.get("exports", False))
                        for s in symbols
                    ]
                )

            # Insert imports — ON CONFLICT DO NOTHING prevents duplicates
            if imports:
                await conn.executemany(
                    """
                    INSERT INTO rsi_imports (repo_id, file_path, imported_path)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (repo_id, file_path, imported_path) DO NOTHING
                    """,
                    [(repo_id, i["file_path"], i["imported_path"]) for i in imports]
                )

            # Insert sensitivities (includes sensitivity_reason)
            if sensitivities:
                await conn.executemany(
                    """
                    INSERT INTO rsi_sensitivity (repo_id, file_path, is_flagged, requires_approval, owners, sensitivity_reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (repo_id, file_path) DO UPDATE SET
                        is_flagged         = EXCLUDED.is_flagged,
                        requires_approval  = EXCLUDED.requires_approval,
                        owners             = EXCLUDED.owners,
                        sensitivity_reason = EXCLUDED.sensitivity_reason
                    """,
                    [
                        (repo_id, s["file_path"], s["is_flagged"], s["requires_approval"],
                         s.get("owners", ""), s.get("sensitivity_reason", ""))
                        for s in sensitivities
                    ]
                )

    counts = f"files={len(files)} symbols={len(symbols)} imports={len(imports)} sensitive={len(sensitivities)}"
    logger.info("Inserted RSI data for %s: %s", repo_id, counts)

async def delete_rsi_for_files(repo_id: str, file_paths: list[str]) -> None:
    """Delete all RSI data corresponding to a list of file paths."""
    if not file_paths:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM rsi_symbol_map  WHERE repo_id = $1 AND file_path = ANY($2)", repo_id, file_paths)
            await conn.execute("DELETE FROM rsi_imports      WHERE repo_id = $1 AND file_path = ANY($2)", repo_id, file_paths)
            await conn.execute("DELETE FROM rsi_sensitivity  WHERE repo_id = $1 AND file_path = ANY($2)", repo_id, file_paths)
            await conn.execute("DELETE FROM rsi_file_map     WHERE repo_id = $1 AND file_path = ANY($2)", repo_id, file_paths)

    logger.info("Deleted RSI data for %d files in %s", len(file_paths), repo_id)

async def delete_rsi_for_repo(repo_id: str) -> None:
    """Obliterate all RSI data for a repository."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM rsi_symbol_map  WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_imports      WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_sensitivity  WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_file_map     WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_repo_summary WHERE repo_id = $1", repo_id)
    logger.info("Deleted all RSI data for repo %s", repo_id)

async def get_file_metadata(repo_id: str, file_paths: list[str]) -> dict:
    """Return role/description/language for each file.
    {file_path: {role_tag, file_desc, language}}
    """
    if not file_paths:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT file_path, role_tag, file_desc, language
            FROM rsi_file_map
            WHERE repo_id = $1 AND file_path = ANY($2)
            """,
            repo_id, file_paths,
        )
    return {
        r["file_path"]: {
            "role_tag":  r["role_tag"],
            "file_desc": r["file_desc"] or "",
            "language":  r["language"],
        }
        for r in rows
    }


async def get_file_symbols(repo_id: str, file_paths: list[str]) -> dict:
    """Return symbols defined in each file.
    {file_path: ["symbol_name (type)", ...]}
    """
    if not file_paths:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT file_path, symbol_name, symbol_type
            FROM rsi_symbol_map
            WHERE repo_id = $1 AND file_path = ANY($2)
            ORDER BY file_path, start_line
            """,
            repo_id, file_paths,
        )
    result: dict[str, list[str]] = {p: [] for p in file_paths}
    for r in rows:
        result.setdefault(r["file_path"], []).append(
            f"{r['symbol_name']} ({r['symbol_type']})"
        )
    return result


async def get_direct_imports(repo_id: str, file_paths: list[str]) -> dict:
    """Return what each file directly imports.
    {file_path: [imported_path, ...]}
    """
    if not file_paths:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT file_path, imported_path
            FROM rsi_imports
            WHERE repo_id = $1 AND file_path = ANY($2)
            ORDER BY file_path
            """,
            repo_id, file_paths,
        )
    result: dict[str, list[str]] = {p: [] for p in file_paths}
    for r in rows:
        result.setdefault(r["file_path"], []).append(r["imported_path"])
    return result


async def search_symbols(repo_id: str, symbol_names: list[str]) -> list[str]:
    """
    Search for files that define the given symbols.
    Returns a unique list of file paths.
    """
    if not symbol_names:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT file_path
            FROM rsi_symbol_map
            WHERE repo_id = $1 AND symbol_name = ANY($2)
            """,
            repo_id, symbol_names
        )
    return [row["file_path"] for row in rows]

async def check_sensitivity(repo_id: str, file_paths: list[str]) -> dict:
    """
    Check multiple files against the sensitivity map.
    Returns {file_path: {requires_approval, is_flagged, sensitivity_reason}} for flagged files.
    """
    if not file_paths:
        return {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT file_path, requires_approval, is_flagged, sensitivity_reason
            FROM rsi_sensitivity
            WHERE repo_id = $1 AND file_path = ANY($2)
            """,
            repo_id, file_paths
        )

    results = {}
    for row in rows:
        if row["is_flagged"] or row["requires_approval"]:
            results[row["file_path"]] = {
                "requires_approval":  row["requires_approval"],
                "is_flagged":         row["is_flagged"],
                "sensitivity_reason": row["sensitivity_reason"] or "",
            }
    return results

async def get_file_shas(repo_id: str, file_paths: list[str]) -> dict:
    """Return current indexed SHAs for files to check if they need stale delta updates."""
    if not file_paths:
        return {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT file_path, file_sha FROM rsi_file_map WHERE repo_id = $1 AND file_path = ANY($2)",
            repo_id, file_paths
        )
    return {r["file_path"]: r["file_sha"] for r in rows}

async def get_importers(repo_id: str, file_paths: list[str]) -> dict:
    """
    Find files that directly import the given file_paths (1-hop).
    Returns {target_file: [list_of_files_that_import_it]}.
    Uses a LIKE match on the stem but post-filters to reduce false positives.
    """
    if not file_paths:
        return {}

    pool = await get_pool()
    results = {path: [] for path in file_paths}

    async with pool.acquire() as conn:
        for path in file_paths:
            stem = Path(path).stem
            like_pattern = f"%{stem}%"
            rows = await conn.fetch(
                """
                SELECT file_path, imported_path
                FROM rsi_imports
                WHERE repo_id = $1 AND imported_path LIKE $2
                """,
                repo_id, like_pattern
            )
            suffix_re = re.compile(rf"(^|[/\\.])({re.escape(stem)})(\.[a-z]+)?$", re.IGNORECASE)
            results[path] = [r["file_path"] for r in rows if suffix_re.search(r["imported_path"])]

    return results

async def get_transitive_importers(
    repo_id: str,
    file_paths: list[str],
    max_depth: int = 3,
) -> dict:
    """
    Find all files that transitively import the given file_paths up to max_depth hops.

    Returns {target_file: [(importer_file_path, hop_depth), ...]}.

    Depth 1 = direct importer, depth 2 = imports a direct importer, etc.
    Uses LIKE + regex for each hop so module path variations (dots vs slashes) are handled.
    """
    if not file_paths:
        return {}

    pool = await get_pool()
    results: dict[str, list[tuple[str, int]]] = {path: [] for path in file_paths}

    async with pool.acquire() as conn:
        for target_path in file_paths:
            seen: set[str] = set()
            frontier: list[str] = [target_path]
            all_importers: list[tuple[str, int]] = []

            for depth in range(1, max_depth + 1):
                if not frontier:
                    break

                next_frontier: list[str] = []
                for fp in frontier:
                    stem = Path(fp).stem
                    like_pattern = f"%{stem}%"
                    rows = await conn.fetch(
                        """
                        SELECT file_path, imported_path
                        FROM rsi_imports
                        WHERE repo_id = $1 AND imported_path LIKE $2
                        """,
                        repo_id, like_pattern
                    )
                    suffix_re = re.compile(rf"(^|[/\\.])({re.escape(stem)})(\.[a-z]+)?$", re.IGNORECASE)
                    for r in rows:
                        if suffix_re.search(r["imported_path"]) and r["file_path"] not in seen:
                            seen.add(r["file_path"])
                            all_importers.append((r["file_path"], depth))
                            next_frontier.append(r["file_path"])

                frontier = next_frontier

            results[target_path] = all_importers

    return results

async def get_monitored_repos() -> list[str]:
    """Return all repo_ids that have RSI data in the database."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT repo_id FROM rsi_file_map ORDER BY repo_id")
    return [r["repo_id"] for r in rows]

async def upsert_repo_summary(
    repo_id: str,
    description: str,
    primary_language: str,
    tech_stack: list[str],
    entry_points: list[str],
    total_files: int,
) -> None:
    """Insert or update the repo-level structural summary."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO rsi_repo_summary
                (repo_id, description, primary_language, tech_stack, entry_points, total_files, last_indexed_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (repo_id) DO UPDATE SET
                description      = EXCLUDED.description,
                primary_language = EXCLUDED.primary_language,
                tech_stack       = EXCLUDED.tech_stack,
                entry_points     = EXCLUDED.entry_points,
                total_files      = EXCLUDED.total_files,
                last_indexed_at  = now()
            """,
            repo_id, description, primary_language, tech_stack, entry_points, total_files
        )
    logger.info("Upserted repo summary for %s", repo_id)

async def get_repo_summary(repo_id: str) -> dict | None:
    """Fetch the repo-level structural summary, or None if not yet indexed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT description, primary_language, tech_stack, entry_points, total_files, last_indexed_at
            FROM rsi_repo_summary
            WHERE repo_id = $1
            """,
            repo_id
        )
    return dict(row) if row else None

async def store_fix_job(repo_id: str, pr_url: str, error_logs: str) -> None:
    """Persist a CI fixer job's error_logs → PR URL mapping for later memory recall."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_fix_jobs (repo_id, pr_url, error_logs)
            VALUES ($1, $2, $3)
            """,
            repo_id, pr_url, error_logs,
        )
    logger.info("Stored fix job for %s → %s", repo_id, pr_url)


async def get_fix_job_by_pr_url(pr_url: str) -> dict | None:
    """Look up the error_logs for a given PR URL. Returns None if not found."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT repo_id, error_logs, created_at FROM agent_fix_jobs WHERE pr_url = $1",
            pr_url,
        )
    return dict(row) if row else None


async def atomic_replace_rsi_data(
    repo_id: str,
    files: list[dict],
    symbols: list[dict],
    imports: list[dict],
    sensitivities: list[dict],
) -> None:
    """R4: Atomically replace all RSI data for a repo in a single transaction.
    If any step fails, the old data is preserved (transaction rolls back)."""
    if not files:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete old data
            await conn.execute("DELETE FROM rsi_symbol_map WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_imports     WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_sensitivity WHERE repo_id = $1", repo_id)
            await conn.execute("DELETE FROM rsi_file_map    WHERE repo_id = $1", repo_id)

            # Insert new data (includes file_desc + last_indexed_at)
            await conn.executemany(
                """
                INSERT INTO rsi_file_map
                    (repo_id, file_path, role_tag, language, file_sha, line_count, file_desc, last_indexed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                """,
                [
                    (repo_id, f["file_path"], f["role_tag"], f["language"],
                     f["file_sha"], f["line_count"], f.get("file_desc", ""))
                    for f in files
                ]
            )

            if symbols:
                await conn.executemany(
                    """
                    INSERT INTO rsi_symbol_map
                        (repo_id, file_path, symbol_name, symbol_type, start_line, end_line, exports)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (repo_id, file_path, symbol_name, symbol_type) DO NOTHING
                    """,
                    [
                        (repo_id, s["file_path"], s["symbol_name"], s["symbol_type"],
                         s["start_line"], s["end_line"], s.get("exports", False))
                        for s in symbols
                    ]
                )

            if imports:
                await conn.executemany(
                    """
                    INSERT INTO rsi_imports (repo_id, file_path, imported_path)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (repo_id, file_path, imported_path) DO NOTHING
                    """,
                    [(repo_id, i["file_path"], i["imported_path"]) for i in imports]
                )

            if sensitivities:
                await conn.executemany(
                    """
                    INSERT INTO rsi_sensitivity
                        (repo_id, file_path, is_flagged, requires_approval, owners, sensitivity_reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (repo_id, s["file_path"], s["is_flagged"], s["requires_approval"],
                         s.get("owners", ""), s.get("sensitivity_reason", ""))
                        for s in sensitivities
                    ]
                )

    counts = f"files={len(files)} symbols={len(symbols)} imports={len(imports)} sensitive={len(sensitivities)}"
    logger.info("Atomic RSI replace for %s: %s", repo_id, counts)
