CREATE TABLE IF NOT EXISTS bot_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  admin_id TEXT NOT NULL,
  member_ids TEXT NOT NULL,
  reply_mode TEXT NOT NULL,
  goal TEXT,
  memory TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bot_groups_user ON bot_groups(user_id, id);

CREATE TABLE IF NOT EXISTS bot_group_turns (
  group_id TEXT NOT NULL REFERENCES bot_groups(group_id) ON DELETE CASCADE,
  request_id TEXT NOT NULL,
  input_json TEXT NOT NULL,
  lease_token TEXT,
  lease_until INTEGER NOT NULL,
  finished INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(group_id, request_id)
);

CREATE TABLE IF NOT EXISTS bot_group_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  group_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  slot TEXT NOT NULL,
  role TEXT NOT NULL,
  agent_id TEXT,
  text TEXT NOT NULL,
  thread_id TEXT,
  created_at INTEGER NOT NULL,
  UNIQUE(group_id, request_id, slot),
  FOREIGN KEY(group_id, request_id) REFERENCES bot_group_turns(group_id, request_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bot_messages_group ON bot_group_messages(group_id, id);

CREATE TABLE IF NOT EXISTS bot_group_drafts (
  group_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  slot TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY(group_id, request_id, slot),
  FOREIGN KEY(group_id, request_id) REFERENCES bot_group_turns(group_id, request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS thread_compaction_boundaries (
  thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
  message_id TEXT NOT NULL,
  PRIMARY KEY(thread_id, message_id)
);

CREATE TABLE IF NOT EXISTS bot_avatar_photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  photo_id TEXT NOT NULL,
  name TEXT NOT NULL,
  mime TEXT NOT NULL,
  content BLOB NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE(user_id, photo_id)
);
CREATE INDEX IF NOT EXISTS idx_bot_avatar_owner_page ON bot_avatar_photos(user_id, id DESC);

UPDATE _schema_version SET version = 26;
