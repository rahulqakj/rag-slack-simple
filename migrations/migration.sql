-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable pg_textsearch extension for BM25 ranking
CREATE EXTENSION IF NOT EXISTS pg_textsearch;

-- Create knowledge_chunks table
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY,
    content TEXT,
    embedding VECTOR(768),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create chat_history table
CREATE TABLE IF NOT EXISTS chat_history (
    id UUID PRIMARY KEY,
    session_id UUID,
    user_message TEXT,
    assistant_message TEXT,
    embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY,
    chat_id UUID REFERENCES chat_history(id),
    query TEXT,
    answer TEXT,
    label BOOLEAN, -- true=good, false=not good
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create analytics table for tracking
CREATE TABLE IF NOT EXISTS analytics (
    id UUID PRIMARY KEY,
    session_id UUID,
    query TEXT,
    response_time_ms INTEGER,
    sources_used JSONB,
    feedback_score BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Generic async job queue to support background processing
CREATE TABLE IF NOT EXISTS async_jobs (
    id UUID PRIMARY KEY,
    job_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress JSONB,
    result JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_async_jobs_status ON async_jobs(status);

-- ==========================================
-- Slack knowledge base schema
-- ==========================================

-- Catalog of Slack workspaces/channels we ingest
CREATE TABLE IF NOT EXISTS slack_channels (
    slack_id TEXT PRIMARY KEY, -- e.g. C6MNKM087
    name TEXT,
    is_private BOOLEAN,
    topic TEXT,
    purpose TEXT,
    internal_metadata JSONB,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Catalog of Slack users referenced in the messages
CREATE TABLE IF NOT EXISTS slack_users (
    slack_id TEXT PRIMARY KEY, -- e.g. U02ARTKMXM4
    username TEXT,
    display_name TEXT,
    real_name TEXT,
    email TEXT,
    avatar_url TEXT,
    is_bot BOOLEAN,
    internal_metadata JSONB,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Track ingestion runs so we can trace embeddings back to their source
CREATE TABLE IF NOT EXISTS slack_ingestion_runs (
    id UUID PRIMARY KEY,
    source_folder TEXT,
    workspace_domain TEXT NOT NULL DEFAULT 'kitabisa',
    embed_model TEXT,
    chunk_strategy TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT,
    stats JSONB
);

-- Raw Slack messages (one row per Slack event)
CREATE TABLE IF NOT EXISTS slack_messages (
    ts TEXT PRIMARY KEY, -- Slack timestamp (e.g. 1747212297.560629)
    channel_id TEXT REFERENCES slack_channels(slack_id) ON DELETE CASCADE,
    user_id TEXT REFERENCES slack_users(slack_id),
    ingestion_run_id UUID REFERENCES slack_ingestion_runs(id),
    thread_ts TEXT, -- Thread root timestamp (matches ts for root messages)
    parent_ts TEXT, -- Direct parent; NULL for root-level posts
    text TEXT,
    raw_json JSONB,
    posted_at TIMESTAMP,
    last_edited_at TIMESTAMP,
    message_type TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_slack_messages_channel ON slack_messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_slack_messages_thread ON slack_messages(thread_ts);
CREATE INDEX IF NOT EXISTS idx_slack_messages_posted_at ON slack_messages(posted_at);

-- Embedding chunks derived from Slack messages
CREATE TABLE IF NOT EXISTS slack_message_chunks (
    id UUID PRIMARY KEY,
    message_ts TEXT REFERENCES slack_messages(ts) ON DELETE CASCADE,
    ingestion_run_id UUID REFERENCES slack_ingestion_runs(id),
    chunk_index INTEGER,
    chunk_text TEXT,
    embedding VECTOR(768),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (message_ts, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_slack_message_chunks_message_ts ON slack_message_chunks(message_ts);
CREATE INDEX IF NOT EXISTS idx_slack_message_chunks_ingestion ON slack_message_chunks(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_slack_message_chunks_embedding ON slack_message_chunks USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);

-- Optional vector index for knowledge chunks to accelerate similarity search
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding ON knowledge_chunks USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);

-- BM25 indexes for pg_textsearch (full-text search ranking)
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_bm25 ON knowledge_chunks USING bm25(content) WITH (text_config='english');
CREATE INDEX IF NOT EXISTS idx_chat_history_bm25 ON chat_history USING bm25(user_message) WITH (text_config='english');

-- Helpful view: expose enriched message context + permalinks for retrieval metadata
CREATE OR REPLACE VIEW slack_message_enriched AS
SELECT
    m.ts AS message_ts,
    m.channel_id,
    c.name AS channel_name,
    m.user_id,
    u.display_name AS user_display_name,
    u.real_name AS user_real_name,
    m.text,
    m.thread_ts,
    m.parent_ts,
    m.posted_at,
    m.message_type,
    m.metadata,
    format(
        'https://%s.slack.com/archives/%s/p%s',
        COALESCE(r.workspace_domain, 'kitabisa'),
        m.channel_id,
        LPAD(regexp_replace(m.ts, '\.', '', 'g'), 16, '0')
    ) AS message_permalink,
    CASE
        WHEN m.thread_ts IS NULL OR m.thread_ts = m.ts THEN NULL
        ELSE format(
            'https://%s.slack.com/archives/%s/p%s',
            COALESCE(r.workspace_domain, 'kitabisa'),
            m.channel_id,
            LPAD(regexp_replace(m.thread_ts, '\.', '', 'g'), 16, '0')
        )
    END AS thread_permalink,
    root.user_id AS thread_owner_id,
    root_user.display_name AS thread_owner_display_name,
    root.text AS thread_root_text
FROM slack_messages m
LEFT JOIN slack_channels c ON c.slack_id = m.channel_id
LEFT JOIN slack_users u ON u.slack_id = m.user_id
LEFT JOIN slack_messages root ON root.ts = COALESCE(m.thread_ts, m.ts)
LEFT JOIN slack_users root_user ON root_user.slack_id = root.user_id
LEFT JOIN slack_ingestion_runs r ON r.id = COALESCE(m.ingestion_run_id, root.ingestion_run_id);

-- Helpful view: aggregate replies under each thread root with permalinks
CREATE OR REPLACE VIEW slack_thread_summary AS
SELECT
    root.ts AS thread_ts,
    root.channel_id,
    c.name AS channel_name,
    format(
        'https://%s.slack.com/archives/%s/p%s',
        COALESCE(r.workspace_domain, 'kitabisa'),
        root.channel_id,
        LPAD(regexp_replace(root.ts, '\.', '', 'g'), 16, '0')
    ) AS thread_permalink,
    root.user_id AS thread_owner_id,
    root_user.display_name AS thread_owner_display_name,
    root.text AS thread_root_text,
    root.posted_at AS thread_started_at,
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'message_ts', reply.ts,
                    'user_id', reply.user_id,
                    'display_name', reply_user.display_name,
                    'text', reply.text,
                    'posted_at', reply.posted_at,
                    'permalink', format(
                        'https://%s.slack.com/archives/%s/p%s',
                        COALESCE(r.workspace_domain, 'kitabisa'),
                        reply.channel_id,
                        LPAD(regexp_replace(reply.ts, '\.', '', 'g'), 16, '0')
                    )
                )
                ORDER BY reply.posted_at NULLS LAST, reply.ts
            )
            FROM slack_messages reply
            LEFT JOIN slack_users reply_user ON reply_user.slack_id = reply.user_id
            WHERE reply.thread_ts = root.ts AND reply.ts <> root.ts
        ),
        '[]'::jsonb
    ) AS replies
FROM slack_messages root
LEFT JOIN slack_channels c ON c.slack_id = root.channel_id
LEFT JOIN slack_users root_user ON root_user.slack_id = root.user_id
LEFT JOIN slack_ingestion_runs r ON r.id = root.ingestion_run_id
WHERE root.thread_ts IS NULL OR root.thread_ts = root.ts;
