-- PostgreSQL schema for ScholarMind Memory (chat-agent only)
-- All primary keys use VARCHAR(64) to match Python uuid string IDs

CREATE TABLE IF NOT EXISTS conversations (
  id         VARCHAR(64) PRIMARY KEY,
  user_id    VARCHAR(64) NOT NULL,
  title      VARCHAR(256),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);

CREATE TABLE IF NOT EXISTS messages (
  id              VARCHAR(64) PRIMARY KEY,
  conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            VARCHAR(16) NOT NULL,            -- user | assistant | system
  content         TEXT NOT NULL,
  citations       JSONB,                           -- [{paper_id, page, chunk_id, image_key}]
  created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
