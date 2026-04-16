"""
RSI Builder pipeline — full repository index building and delta updates.
Replaces the old pgvector/RAG vector ingestion.
"""

import hashlib
import logging
import os
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

import httpx
from config import get_settings
from rsi import db, parser

logger = logging.getLogger("devops_agent.rsi.builder")

# Files / directories to skip during RSI ingestion
SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    ".next", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
}
SKIP_EXTENSIONS = {
    ".lock", ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bin", ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo",
}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock"}

_ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "index.ts", "index.js", "index.tsx", "index.jsx",
    "main.ts", "main.js", "__main__.py",
}

def _generate_repo_summary(repo_full_name: str, all_files: list[dict]) -> dict:
    """
    Build a heuristic CLAUDE.md-style project summary from the indexed file list.
    Called once after cold_start_build — no LLM cost.
    """
    repo_name = repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name

    role_counts  = Counter(f["role_tag"] for f in all_files)
    lang_counts  = Counter(f["language"] for f in all_files if f.get("language"))
    primary_lang = lang_counts.most_common(1)[0][0] if lang_counts else "unknown"

    # Tech stack — non-trivial extensions only
    skip_exts = {"", "md", "txt", "json", "yaml", "yml", "toml", "lock", "env"}
    tech_stack = sorted({f["language"] for f in all_files if f.get("language") not in skip_exts})[:10]

    # Top-level directories
    top_dirs: set[str] = set()
    for f in all_files:
        parts = Path(f["file_path"]).parts
        if len(parts) > 1:
            top_dirs.add(parts[0])

    # Entry points
    entry_points = [
        f["file_path"] for f in all_files
        if Path(f["file_path"]).name in _ENTRY_POINT_NAMES
    ][:5]

    src   = role_counts.get("source", 0)
    tests = role_counts.get("test",   0)
    infra = role_counts.get("infra",  0)
    total = len(all_files)

    dir_str  = ", ".join(sorted(top_dirs)[:6]) or "none"
    lang_str = ", ".join(l for l, _ in lang_counts.most_common(3)) or primary_lang
    ep_str   = ", ".join(entry_points) or "none detected"

    description = (
        f"{repo_name}: {total} files total ({src} source, {tests} test, {infra} infra). "
        f"Primary language: {primary_lang}. "
        f"Top-level directories: {dir_str}. "
        f"Languages used: {lang_str}. "
        f"Entry points: {ep_str}."
    )

    return {
        "description":      description,
        "primary_language": primary_lang,
        "tech_stack":       tech_stack,
        "entry_points":     entry_points,
        "total_files":      total,
    }

def _should_skip(path: Path) -> bool:
    """Check if a file should be excluded from ingestion."""
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    if path.name in SKIP_FILES:
        return True
    return False

def _compute_git_sha(content_bytes: bytes) -> str:
    """Compute the git blob SHA-1 hash for a given content."""
    # B2: use a real null byte b"\x00", not the literal two-char sequence "\\0"
    header = f"blob {len(content_bytes)}\0".encode("utf-8")
    return hashlib.sha1(header + content_bytes).hexdigest()

async def _get_default_branch(owner: str, repo: str, token: str) -> str:
    """B5/B21: Fetch the repository's default branch from the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json().get("default_branch", "main")
    return "main"

async def cold_start_build(repo_full_name: str, commit_hash: str = "HEAD", github_token: str = "") -> int:
    """
    Full repo ingestion — downloads tarball, strips ignored files, parses via RSI parser,
    and inserts into PostgreSQL.
    R4: Uses atomic_replace_rsi_data so a mid-flight failure preserves old data.
    Returns the number of files inserted.
    """
    settings = get_settings()
    token = github_token or settings.github_token
    logger.info("Cold-start RSI build for %s", repo_full_name)

    # 1. Initialize schema (idempotent)
    await db.init_db()

    # 2. Download repo tarball — B5: detect default branch, don't hardcode "main"
    owner, repo = repo_full_name.split("/")
    default_branch = await _get_default_branch(owner, repo, token)
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{default_branch}"
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Extract and process files
    all_files = []
    all_symbols = []
    all_imports = []
    all_sensitivities = []

    # B22: stream tarball to a temp file instead of loading entire content into memory
    with tempfile.TemporaryDirectory() as tmp_dir:
        tar_path = os.path.join(tmp_dir, "repo.tar.gz")
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with open(tar_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        logger.info("Successfully downloaded repo tarball from %s", url)

        # B17: use filter="data" to guard against path-traversal in tarballs (Python 3.12+)
        with tarfile.open(tar_path, mode="r:gz") as tar:
            tar.extractall(path=tmp_dir, filter="data")

        # The tarball extracts to a single top-level directory
        extracted = [p for p in Path(tmp_dir).iterdir() if p.is_dir() and p.name != "__MACOSX"]
        root = extracted[0] if extracted else Path(tmp_dir)

        for file_path in root.rglob("*"):
            if file_path.is_dir():
                continue
            relative = file_path.relative_to(root)
            if _should_skip(relative):
                continue

            try:
                content_bytes = file_path.read_bytes()
                content = content_bytes.decode("utf-8")
            except Exception:
                continue

            if not content.strip() or len(content) > 500_000:
                continue

            file_sha = _compute_git_sha(content_bytes)

            parsed = parser.parse_file(content, str(relative), file_sha)

            all_files.append(parsed["file"])
            all_symbols.extend(parsed["symbols"])
            all_imports.extend(parsed["imports"])
            all_sensitivities.append(parsed["sensitivity"])

    logger.info("Parsed %d files for %s", len(all_files), repo_full_name)

    if not all_files:
        return 0

    # 4. R4: Atomically replace RSI data — if this fails, old data is preserved
    await db.atomic_replace_rsi_data(
        repo_full_name,
        all_files,
        all_symbols,
        all_imports,
        all_sensitivities
    )

    # 5. Generate and store the repo-level structural summary
    summary = _generate_repo_summary(repo_full_name, all_files)
    await db.upsert_repo_summary(
        repo_full_name,
        summary["description"],
        summary["primary_language"],
        summary["tech_stack"],
        summary["entry_points"],
        summary["total_files"],
    )

    logger.info("Cold-start RSI build complete: inserted %d files for %s", len(all_files), repo_full_name)
    return len(all_files)


async def delta_update(
    repo_full_name: str,
    commits: list[dict],
    github_token: str = "",
    before: str = "",
    after: str = "",
) -> dict:
    """
    Incremental update after a push.

    Prefers the GitHub compare API (before...after) for a complete file list —
    the commits array caps each commit at 20 files, silently dropping the rest.
    Falls back to the commits array if the compare API fails or SHAs are absent.

    `before` / `after` come from the push webhook payload's top-level fields.
    """
    settings = get_settings()
    token = github_token or settings.github_token
    await db.init_db()

    added: set[str]    = set()
    modified: set[str] = set()
    removed: set[str]  = set()

    owner, repo = repo_full_name.split("/")
    _NULL_SHA = "0" * 40   # GitHub sends this as `before` on the very first push

    used_compare_api = False

    if before and after and before != _NULL_SHA:
        compare_url = f"https://api.github.com/repos/{owner}/{repo}/compare/{before}...{after}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(compare_url, headers=headers)
            if resp.status_code == 200:
                for f in resp.json().get("files", []):
                    fname  = f["filename"]
                    status = f.get("status", "modified")
                    if status == "removed":
                        removed.add(fname)
                    elif status == "added":
                        added.add(fname)
                    else:  # modified, renamed, copied
                        modified.add(fname)
                        # renamed: old path is effectively removed
                        if f.get("previous_filename"):
                            removed.add(f["previous_filename"])
                used_compare_api = True
                logger.info(
                    "RSI delta update for %s via compare API: +%d ~%d -%d files",
                    repo_full_name, len(added), len(modified), len(removed),
                )
            else:
                logger.warning(
                    "Compare API returned %d for %s — falling back to commits array",
                    resp.status_code, repo_full_name,
                )
        except Exception as e:
            logger.warning("Compare API failed for %s (%s) — falling back to commits array", repo_full_name, e)

    if not used_compare_api:
        for commit in commits:
            added.update(commit.get("added", []))
            modified.update(commit.get("modified", []))
            removed.update(commit.get("removed", []))
        logger.info(
            "RSI delta update for %s via commits array: +%d ~%d -%d files",
            repo_full_name, len(added), len(modified), len(removed),
        )

    # 1. Handle removals
    if removed:
        await db.delete_rsi_for_files(repo_full_name, list(removed))

    # 2. Handle additions & modifications
    files_to_parse = list(modified | added)

    # B18: delete BOTH modified AND added files before re-inserting to prevent
    # duplicate symbols/imports on replayed pushes or parallel cold-starts
    files_to_delete = list(modified | added)
    if files_to_delete:
        await db.delete_rsi_for_files(repo_full_name, files_to_delete)

    # 3. Fetch, parse, insert
    # Use `after` SHA (most accurate) → last commit SHA → default branch fallback
    push_ref = after or (commits[-1].get("id") if commits else "") or "main"

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3.raw"}

    all_files = []
    all_symbols = []
    all_imports = []
    all_sensitivities = []

    async with httpx.AsyncClient(timeout=60) as client:
        for file_path in files_to_parse:
            if _should_skip(Path(file_path)):
                continue

            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={push_ref}"
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                content_bytes = resp.content
                content = content_bytes.decode("utf-8")
                logger.info("Fetched file %s for RSI delta parsing (Length: %d bytes)", file_path, len(content_bytes))
            except httpx.HTTPStatusError as e:
                logger.warning("Failed to fetch %s (HTTP %s)", file_path, e.response.status_code)
                continue
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", file_path, e)
                continue

            if not content.strip() or len(content) > 500_000:
                continue

            file_sha = _compute_git_sha(content_bytes)

            parsed = parser.parse_file(content, file_path, file_sha)

            all_files.append(parsed["file"])
            all_symbols.extend(parsed["symbols"])
            all_imports.extend(parsed["imports"])
            all_sensitivities.append(parsed["sensitivity"])

    if all_files:
        await db.insert_rsi_data(
            repo_full_name,
            all_files,
            all_symbols,
            all_imports,
            all_sensitivities
        )

    summary = {
        "removed": len(removed),
        "modified": len(modified),
        "added": len(added),
        "files_inserted": len(all_files),
    }
    logger.info("RSI Delta update complete: %s", summary)
    return summary

async def partial_reindex_pr(repo_full_name: str, pr_number: int, github_token: str = "") -> dict:
    """
    Partial re-index triggered on PR open/sync.
    Fetches the list of changed files via GitHub API, checks SHAs, and only re-scans stale files.
    L4: Uses the PR's head commit SHA (not per-file blob SHA) when fetching file contents.
    """
    settings = get_settings()
    token = github_token or settings.github_token
    await db.init_db()

    owner, repo = repo_full_name.split("/")

    # L4: Fetch the PR to get the head commit SHA once
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    head_sha = "main"  # fallback
    async with httpx.AsyncClient(timeout=60) as client:
        pr_resp = await client.get(pr_url, headers=pr_headers)
        if pr_resp.status_code == 200:
            head_sha = pr_resp.json().get("head", {}).get("sha", head_sha)
        else:
            logger.warning("Failed to fetch PR #%d metadata: %s", pr_number, pr_resp.text)

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning("Failed to fetch PR files: %s", resp.text)
            return {}
        pr_files = resp.json()

    # Get current SHAs from RSI to see if they are stale
    file_paths = [f["filename"] for f in pr_files]
    existing_shas = await db.get_file_shas(repo_full_name, file_paths)

    stale_files = []
    removed_files = []

    for f in pr_files:
        path = f["filename"]
        if f["status"] == "removed":
            removed_files.append(path)
        else:
            if existing_shas.get(path) != f["sha"]:
                stale_files.append({"path": path, "sha": f["sha"]})

    if removed_files:
        await db.delete_rsi_for_files(repo_full_name, removed_files)

    if not stale_files:
        logger.info("RSI PR Re-index: No stale files found for PR #%d", pr_number)
        return {"stale": 0, "removed": len(removed_files)}

    # Remove stale file data
    stale_paths = [s["path"] for s in stale_files]
    await db.delete_rsi_for_files(repo_full_name, stale_paths)

    all_files = []
    all_symbols = []
    all_imports = []
    all_sensitivities = []

    async with httpx.AsyncClient(timeout=60) as client:
        for sf in stale_files:
            if _should_skip(Path(sf["path"])):
                continue

            # L4: Use head_sha (commit SHA), not sf["sha"] (blob SHA)
            raw_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{sf['path']}?ref={head_sha}"
            resp = await client.get(raw_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3.raw"})
            if resp.status_code != 200:
                continue

            content = resp.content.decode("utf-8")
            if not content.strip() or len(content) > 500_000:
                continue

            file_sha = _compute_git_sha(resp.content)
            parsed = parser.parse_file(content, sf["path"], file_sha)
            all_files.append(parsed["file"])
            all_symbols.extend(parsed["symbols"])
            all_imports.extend(parsed["imports"])
            all_sensitivities.append(parsed["sensitivity"])

    if all_files:
        await db.insert_rsi_data(
            repo_full_name, all_files, all_symbols, all_imports, all_sensitivities
        )

    logger.info("RSI PR Re-index complete: %d stale files updated, %d removed", len(stale_files), len(removed_files))
    return {"stale": len(stale_files), "removed": len(removed_files)}
