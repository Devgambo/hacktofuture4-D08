CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rsi_file_map (
    repo_id         TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    role_tag        TEXT DEFAULT 'source',
    language        TEXT DEFAULT '',
    file_sha        TEXT NOT NULL,
    line_count      INTEGER DEFAULT 0,
    file_desc       TEXT DEFAULT '',
    last_indexed_at TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (repo_id, file_path)
);

-- B19: unique constraint prevents duplicate symbol rows on replayed inserts
CREATE TABLE IF NOT EXISTS rsi_symbol_map (
    id          SERIAL PRIMARY KEY,
    repo_id     TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL, -- 'function' or 'class'
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    exports     BOOLEAN DEFAULT false,
    UNIQUE (repo_id, file_path, symbol_name, symbol_type)
);

CREATE INDEX IF NOT EXISTS idx_rsi_symbol_map_repo_symbol
    ON rsi_symbol_map (repo_id, symbol_name);

-- B19: unique constraint prevents duplicate import rows on replayed inserts
CREATE TABLE IF NOT EXISTS rsi_imports (
    id            SERIAL PRIMARY KEY,
    repo_id       TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    imported_path TEXT NOT NULL,
    UNIQUE (repo_id, file_path, imported_path)
);

CREATE INDEX IF NOT EXISTS idx_rsi_imports_repo_file
    ON rsi_imports (repo_id, file_path);

-- Index for reverse lookup (who imports a given path)
CREATE INDEX IF NOT EXISTS idx_rsi_imports_imported_path
    ON rsi_imports (repo_id, imported_path);

CREATE TABLE IF NOT EXISTS rsi_sensitivity (
    repo_id            TEXT NOT NULL,
    file_path          TEXT NOT NULL,
    is_flagged         BOOLEAN DEFAULT false,
    requires_approval  BOOLEAN DEFAULT false,
    owners             TEXT DEFAULT '',     -- Comma-separated or JSON string
    sensitivity_reason TEXT DEFAULT '',     -- Short reason why this file is flagged
    PRIMARY KEY (repo_id, file_path)
);

-- ─────────────────────────────────────────────────────────
-- Repo-level structural summary (one record per repo)
-- Generated after cold-start index build.
-- Gives agents a CLAUDE.md-style project overview.
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rsi_repo_summary (
    repo_id          TEXT PRIMARY KEY,
    description      TEXT NOT NULL DEFAULT '',  -- Human-readable project overview
    primary_language TEXT NOT NULL DEFAULT '',
    tech_stack       TEXT[] DEFAULT '{}',        -- Languages/frameworks detected
    entry_points     TEXT[] DEFAULT '{}',        -- Root entry-point file paths
    total_files      INTEGER DEFAULT 0,
    last_indexed_at  TIMESTAMPTZ DEFAULT now(),
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- Auth/session persistence moved from local JSON files into PostgreSQL.
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id              TEXT PRIMARY KEY,
    github_token_ciphertext TEXT NOT NULL,
    github_token_hash       TEXT NOT NULL,
    user_info               JSONB NOT NULL DEFAULT '{}'::jsonb,
    repos                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
    ON user_sessions (expires_at);

CREATE TABLE IF NOT EXISTS repo_credentials (
    session_id              TEXT NOT NULL REFERENCES user_sessions(session_id) ON DELETE CASCADE,
    repo_full_name          TEXT NOT NULL,
    github_token_ciphertext TEXT NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (session_id, repo_full_name)
);

CREATE INDEX IF NOT EXISTS idx_repo_credentials_repo_full_name
    ON repo_credentials (repo_full_name);

CREATE TABLE IF NOT EXISTS repo_webhooks (
    repo_full_name   TEXT PRIMARY KEY,
    webhook_id       BIGINT NOT NULL,
    last_verified_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rsi_symbol_map_repo_file_name_type_key'
    ) THEN
        ALTER TABLE rsi_symbol_map
            ADD CONSTRAINT rsi_symbol_map_repo_file_name_type_key
            UNIQUE (repo_id, file_path, symbol_name, symbol_type);
    END IF;
EXCEPTION WHEN others THEN
    -- Constraint already exists or table is new; ignore
    NULL;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rsi_imports_repo_file_path_key'
    ) THEN
        ALTER TABLE rsi_imports
            ADD CONSTRAINT rsi_imports_repo_file_path_key
            UNIQUE (repo_id, file_path, imported_path);
    END IF;
EXCEPTION WHEN others THEN
    NULL;
END;
$$;

-- ─────────────────────────────────────────────────────────
-- Migrations for existing deployments
-- (new columns added after initial schema was deployed)
-- ─────────────────────────────────────────────────────────

DO $$
BEGIN
    ALTER TABLE rsi_file_map ADD COLUMN IF NOT EXISTS file_desc TEXT DEFAULT '';
    ALTER TABLE rsi_file_map ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMPTZ DEFAULT now();
EXCEPTION WHEN others THEN NULL;
END;
$$;

DO $$
BEGIN
    ALTER TABLE rsi_sensitivity ADD COLUMN IF NOT EXISTS sensitivity_reason TEXT DEFAULT '';
EXCEPTION WHEN others THEN NULL;
END;
$$;

-- Reverse-import index for transitive blast-radius queries
CREATE INDEX IF NOT EXISTS idx_rsi_imports_imported_path
    ON rsi_imports (repo_id, imported_path);

-- ─────────────────────────────────────────────────────────
-- Agent Fix Jobs — persists error_logs → PR URL mapping
-- Survives server restarts; used by _handle_merged_fix_pr
-- to recover original CI error context for episodic memory.
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_fix_jobs (
    id          SERIAL PRIMARY KEY,
    repo_id     TEXT NOT NULL,
    pr_url      TEXT NOT NULL DEFAULT '',
    error_logs  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_fix_jobs_pr_url
    ON agent_fix_jobs (pr_url);

CREATE INDEX IF NOT EXISTS idx_agent_fix_jobs_repo_id
    ON agent_fix_jobs (repo_id);

-- ─────────────────────────────────────────────────────────
-- Agent Episodic Memory — successful fix experiences
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_memory (
    id              SERIAL PRIMARY KEY,
    repo_id         TEXT NOT NULL,
    error_signature TEXT NOT NULL,
    error_logs      TEXT NOT NULL DEFAULT '',
    root_cause      TEXT NOT NULL DEFAULT '',
    fix_summary     TEXT NOT NULL DEFAULT '',
    files_changed   TEXT[] DEFAULT '{}',
    pr_url          TEXT DEFAULT '',
    pr_number       INTEGER,
    language        TEXT DEFAULT '',
    embedding       vector(1024) NOT NULL,
    hit_count       INTEGER DEFAULT 0,
    last_hit_at     TIMESTAMPTZ,
    merged_at       TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- HNSW index for fast approximate nearest-neighbor cosine search
CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding
    ON agent_memory USING hnsw (embedding vector_cosine_ops);

-- Index for repo-scoped queries
CREATE INDEX IF NOT EXISTS idx_agent_memory_repo
    ON agent_memory (repo_id);

-- ─────────────────────────────────────────────────────────
-- Migration: per-user Telegram chat ID
-- Stores the Telegram chat_id for each authenticated user so
-- notifications can be targeted rather than broadcast.
-- ─────────────────────────────────────────────────────────
DO $$
BEGIN
    ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT;
EXCEPTION WHEN others THEN NULL;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_user_sessions_telegram_chat_id
    ON user_sessions (telegram_chat_id)
    WHERE telegram_chat_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────
-- Migration: agent_memory embedding dimension 768 → 1024
-- (BGE-M3 produces 1024-dim vectors; old Nomic/Qwen used 768)
-- Existing memory rows are cleared — they used the wrong model.
-- ─────────────────────────────────────────────────────────
DO $$
DECLARE
    col_typmod integer;
BEGIN
    SELECT atttypmod INTO col_typmod
    FROM pg_attribute
    WHERE attrelid = 'agent_memory'::regclass
      AND attname = 'embedding';

    -- typmod for vector(768) is 768; vector(1024) is 1024
    IF col_typmod IS NOT NULL AND col_typmod = 768 THEN
        DROP INDEX IF EXISTS idx_agent_memory_embedding;
        DELETE FROM agent_memory;  -- stale 768-dim rows are incompatible
        ALTER TABLE agent_memory ALTER COLUMN embedding TYPE vector(1024);
        CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding
            ON agent_memory USING hnsw (embedding vector_cosine_ops);
    END IF;
EXCEPTION WHEN others THEN NULL;
END;
$$;
