"""Multi-turn conversation memory backed by PostgreSQL."""
import uuid
import json
from datetime import datetime
from sqlalchemy import text
from common.db.pg import AsyncSessionLocal
from common.logging import logger


async def get_or_create_conversation(
    user_id: str, conversation_id: str = None, title: str = "新对话"
) -> dict:
    """Get existing conversation or create a new one."""
    async with AsyncSessionLocal() as session:
        if conversation_id:
            result = await session.execute(
                text("SELECT * FROM conversations WHERE id = :id AND user_id = :uid"),
                {"id": conversation_id, "uid": user_id},
            )
            row = result.fetchone()
            if row:
                return dict(row._mapping)

        # Create new conversation
        cid = str(uuid.uuid4())[:12]
        now = datetime.now()
        await session.execute(
            text(
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
                "VALUES (:id, :uid, :title, :now, :now)"
            ),
            {"id": cid, "uid": user_id, "title": title, "now": now},
        )
        await session.commit()
        return {"id": cid, "user_id": user_id, "title": title, "created_at": now, "updated_at": now}


async def add_message(
    conversation_id: str, role: str, content: str, citations: list = None
) -> dict:
    """Append a message to a conversation."""
    async with AsyncSessionLocal() as session:
        msg_id = str(uuid.uuid4())[:12]
        now = datetime.now()
        await session.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content, citations, created_at) "
                "VALUES (:id, :cid, :role, :content, :citations, :now)"
            ),
            {
                "id": msg_id,
                "cid": conversation_id,
                "role": role,
                "content": content,
                "citations": json.dumps(citations or [], ensure_ascii=False),
                "now": now,
            },
        )
        await session.execute(
            text("UPDATE conversations SET updated_at = :now WHERE id = :cid"),
            {"now": now, "cid": conversation_id},
        )
        await session.commit()
        return {"id": msg_id, "conversation_id": conversation_id, "role": role, "content": content}


async def get_history(conversation_id: str, limit: int = 20) -> list[dict]:
    """Get recent messages for a conversation."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT role, content, citations FROM messages "
                "WHERE conversation_id = :cid ORDER BY created_at ASC LIMIT :lim"
            ),
            {"cid": conversation_id, "lim": limit},
        )
        rows = result.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]


async def get_conversations(user_id: str) -> list[dict]:
    """List conversations for a user."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_id = :uid ORDER BY updated_at DESC"
            ),
            {"uid": user_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]
