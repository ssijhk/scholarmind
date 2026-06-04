"""Chat router with real SSE streaming through chat_agent + retrieval services."""
import json
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import List
from datetime import datetime
from app.schemas.chat import (
    ConversationResponse, ConversationCreate, MessageResponse,
    ChatQueryRequest, FeedbackRequest, FeedbackResponse,
)
from common.auth.deps import get_current_user_id
from common.clients.llm import embed_query
from common.config import settings
from common.logging import logger
from common.db.mysql import AsyncSessionLocal
from services.chat_agent import (
    route_intent, get_or_create_conversation, add_message,
    get_history, get_conversations, generate_answer_stream,
)
from services.retrieval import optimize_query, hybrid_search, rerank_chunks
from sqlalchemy import text

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(data: ConversationCreate, user_id: str = Depends(get_current_user_id)):
    conv = await get_or_create_conversation(user_id, title=data.title or "新对话")
    return ConversationResponse(
        id=conv["id"], title=conv["title"], folder_id=data.folder_id,
        paper_ids=data.paper_ids or [], created_at=conv["created_at"], updated_at=conv["updated_at"],
    )

@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(user_id: str = Depends(get_current_user_id)):
    convs = await get_conversations(user_id)
    return [ConversationResponse(id=c["id"], title=c["title"], folder_id="", paper_ids=[], created_at=c["created_at"], updated_at=c["updated_at"]) for c in convs]

@router.get("/conversations/{id}/messages", response_model=List[MessageResponse])
async def list_messages(id: str, user_id: str = Depends(get_current_user_id)):
    msgs = await get_history(id)
    return [MessageResponse(id=i+1, conversation_id=id, role=m["role"], content=m["content"], citations=[], created_at=datetime.now()) for i, m in enumerate(msgs)]


@router.post("/query")
async def chat_query(request: ChatQueryRequest, user_id: str = Depends(get_current_user_id)):
    t0 = time.time()
    prompt_tokens = 0
    completion_tokens = 0
    query_text = request.question

    async def sse_generator():
        nonlocal prompt_tokens, completion_tokens, query_text
        full_answer = ""
        citations_list = []
        chunks = []

        try:
            intent = await route_intent(request.question)
            logger.info(f"Intent: {intent['intent']} for '{request.question[:50]}'")

            history = []
            if request.conversation_id:
                history = await get_history(request.conversation_id)

            if intent["intent"] == "chitchat":
                from common.clients.llm import llm_chat_stream
                messages = [{"role": "system", "content": "You are a helpful academic assistant. Reply concisely in Chinese."}]
                for h in history[-6:]:
                    messages.append({"role": h["role"], "content": h["content"]})
                messages.append({"role": "user", "content": request.question})
                prompt_tokens = sum(len(m["content"]) // 4 for m in messages)
                async for token in llm_chat_stream(messages):
                    full_answer += token
                    completion_tokens += 1
                    yield f"event: token\ndata: {json.dumps({'delta': token})}\n\n"
                yield f"event: done\ndata: {json.dumps({'latency_ms': 0})}\n\n"
                return

            # Query optimization
            optimized = await optimize_query(request.question, history)
            query_text = optimized.get("rewritten", request.question)

            # ---- Multi-query expansion ----
            all_chunks = []
            query_vec = await embed_query(query_text)
            try:
                all_chunks = await hybrid_search(query_text, query_vec, user_id, {})
            except Exception as e:
                logger.warning(f"Hybrid search failed: {e}")

            if settings.ENABLE_MULTI_QUERY and optimized.get("multi_queries"):
                for mq in optimized["multi_queries"][:3]:
                    if mq != query_text:
                        try:
                            mq_vec = await embed_query(mq)
                            extra = await hybrid_search(mq, mq_vec, user_id, {})
                            all_chunks.extend(extra)
                        except Exception:
                            pass
            chunks = all_chunks

            if chunks and settings.ENABLE_RERANK:
                chunks = await rerank_chunks(query_text, chunks)

            # ---- Corrective RAG ----
            if settings.ENABLE_CORRECTIVE_RAG and chunks:
                from services.retrieval import grade_retrieval
                grade = await grade_retrieval(query_text, chunks)
                logger.info(f"CorrectiveRAG score: {grade}")
                if grade.get("score") == "insufficient" and grade.get("action") == "rewrite_query":
                    # Re-search with translated query
                    try:
                        tr_vec = await embed_query(optimized.get("translated", query_text))
                        extra = await hybrid_search(optimized.get("translated", query_text), tr_vec, user_id, {})
                        if extra:
                            chunks.extend(extra)
                            if settings.ENABLE_RERANK:
                                chunks = await rerank_chunks(query_text, chunks)
                    except Exception as e:
                        logger.warning(f"Corrective RAG re-search failed: {e}")

            # Generate answer
            ctx_size = sum(len(ch.get("content_en", "")) for ch in chunks)
            prompt_tokens = (ctx_size // 4) + len(request.question) // 4 + 200

            async for token in generate_answer_stream(request.question, chunks, history):
                full_answer += token
                completion_tokens += 1
                yield f"event: token\ndata: {json.dumps({'delta': token})}\n\n"

            # ---- Self-RAG Reflect ----
            if settings.ENABLE_SELF_RAG_REFLECT and full_answer and chunks:
                try:
                    from services.parsing.prompts import load_prompt
                    template = load_prompt("self_rag_reflect")
                    reflect_prompt = template.replace("{answer}", full_answer).replace(
                        "{sources}", "\n".join(ch.get("content_en", "")[:300] for ch in chunks[:5])
                    )
                    from common.clients.llm import llm_chat
                    reflection = await llm_chat([{"role": "user", "content": reflect_prompt}], temperature=0.0, max_tokens=256)
                    import re
                    m = re.search(r"\{.*\}", reflection, re.DOTALL)
                    if m:
                        reflect_data = json.loads(m.group())
                        if not reflect_data.get("faithful", True):
                            full_answer = reflect_data.get("revised_answer", full_answer)
                            yield f"event: token\ndata: {json.dumps({'delta': '[已自检纠正]'})}\n\n"
                except Exception as e:
                    logger.warning(f"Self-RAG reflection failed: {e}")

            for i, ch in enumerate(chunks[:5]):
                cite = {
                    "paper_id": ch.get("paper_id", ""),
                    "paper_title": ch.get("paper_title", ch.get("paper_id", "")),
                    "page_num": ch.get("page_num", 0), "bbox": "",
                    "chunk_type": ch.get("chunk_type", "text"),
                    "content": (ch.get("content_zh") or ch.get("content_en", ""))[:500],
                    "image_key": ch.get("image_key", ""),
                }
                citations_list.append(cite)
                yield f"event: cite\ndata: {json.dumps(cite)}\n\n"

            yield f"event: done\ndata: {json.dumps({'latency_ms': int((time.time()-t0)*1000)})}\n\n"

        except Exception as e:
            logger.error(f"Chat query failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Persist messages to PG
            if request.conversation_id and full_answer:
                try:
                    await add_message(request.conversation_id, "user", request.question)
                    await add_message(request.conversation_id, "assistant", full_answer, citations_list)
                except Exception as e:
                    logger.error(f"Failed to persist messages: {e}")

            # Write query_log with full metrics
            latency_ms = int((time.time() - t0) * 1000)
            try:
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text(
                            "INSERT INTO query_logs "
                            "(id, user_id, conversation_id, question, rewritten_query, "
                            "retrieved_chunk_ids, top_k, latency_ms, prompt_tokens, completion_tokens, created_at) "
                            "VALUES (:id, :uid, :cid, :q, :rw, :chunks, :tk, :lat, :pt, :ct, NOW())"
                        ),
                        {
                            "id": str(uuid.uuid4())[:12], "uid": user_id,
                            "cid": request.conversation_id or "",
                            "q": request.question,
                            "rw": query_text if query_text != request.question else None,
                            "chunks": json.dumps([ch.get("id", "") for ch in chunks] if chunks else []),
                            "tk": len(chunks),
                            "lat": latency_ms,
                            "pt": prompt_tokens, "ct": completion_tokens,
                        },
                    )
                    await session.commit()
            except Exception as e:
                logger.warning(f"Failed to write query_log: {e}")

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.post("/feedback", response_model=FeedbackResponse)
async def message_feedback(data: FeedbackRequest, user_id: str = Depends(get_current_user_id)):
    """Save user feedback to query_logs. 1=like, -1=dislike."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "UPDATE query_logs SET feedback = :fb "
                    "WHERE id = (SELECT id FROM (SELECT id FROM query_logs WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1 OFFSET :off) AS t)"
                ),
                {"fb": 1 if data.is_positive else -1, "uid": user_id, "off": max(0, data.message_id - 1)},
            )
            await session.commit()
            logger.info(f"Feedback saved: msg_id={data.message_id}, positive={data.is_positive}")
    except Exception as e:
        logger.error(f"Failed to save feedback: {e}")
    return FeedbackResponse(status="success", message="Feedback saved successfully.")
