CREATE TABLE IF NOT EXISTS bot_handoffs (
    slot TEXT PRIMARY KEY,
    pending_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    resume_agent_id TEXT,
    resume_thread_id TEXT,
    origin TEXT,
    expires_at DOUBLE PRECISION,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_handoff_user ON bot_handoffs(user_id);
CREATE INDEX IF NOT EXISTS idx_handoff_agent ON bot_handoffs(agent_id);
CREATE INDEX IF NOT EXISTS idx_handoff_thread ON bot_handoffs(thread_id);
CREATE INDEX IF NOT EXISTS idx_handoff_session ON bot_handoffs(session_key);
CREATE INDEX IF NOT EXISTS idx_handoff_member ON bot_handoffs(resume_agent_id);
CREATE INDEX IF NOT EXISTS idx_handoff_member_thread ON bot_handoffs(resume_thread_id);
CREATE INDEX IF NOT EXISTS idx_handoff_origin ON bot_handoffs(origin);
CREATE INDEX IF NOT EXISTS idx_handoff_expiry ON bot_handoffs(expires_at);

CREATE TABLE IF NOT EXISTS bot_handoff_deadlines (
    pending_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    origin TEXT,
    expires_at DOUBLE PRECISION NOT NULL,
    next_attempt DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_handoff_deadline_due ON bot_handoff_deadlines(next_attempt);

UPDATE _schema_version SET version = 29;
