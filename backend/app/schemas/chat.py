from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ConversationCreate(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[str] = None
    paper_ids: Optional[List[str]] = None

class ConversationResponse(BaseModel):
    id: str
    title: str
    folder_id: Optional[str] = None
    paper_ids: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class CitationResponse(BaseModel):
    paper_id: str
    paper_title: str
    page_num: int
    bbox: str
    chunk_type: str  # "text", "table", "figure", "formula"
    content: str
    image_key: Optional[str] = None

class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    role: str  # "user", "assistant"
    content: str
    citations: Optional[List[CitationResponse]] = None
    created_at: Optional[datetime] = None

class ChatQueryRequest(BaseModel):
    question: str
    conversation_id: str = ""
    scope_type: str = "all"  # "all", "folder", "papers"
    folder_id: Optional[str] = None
    paper_ids: Optional[List[str]] = None

class FeedbackRequest(BaseModel):
    message_id: int
    is_positive: bool
    reason: Optional[str] = None

class FeedbackResponse(BaseModel):
    status: str
    message: str
