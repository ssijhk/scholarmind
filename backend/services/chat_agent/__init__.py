"""Chat Agent service — intent routing, memory, citation-aware generation."""
from .intent_router import route_intent
from .memory import get_or_create_conversation, add_message, get_history, get_conversations
from .generator import generate_answer_with_citations, generate_review_stream, generate_answer_stream

__all__ = [
    "route_intent",
    "get_or_create_conversation",
    "add_message",
    "get_history",
    "get_conversations",
    "generate_answer_with_citations",
    "generate_review_stream",
    "generate_answer_stream",
]
