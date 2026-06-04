from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class QueryLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    question: str
    rewritten_query: Optional[str] = None
    latency_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    retrieved_chunk_ids: Optional[List[str]] = None
    feedback: Optional[int] = None
    created_at: Optional[datetime] = None

class AccessLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    path: str
    method: str
    status_code: int
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None

class StatsOverviewResponse(BaseModel):
    paper_count: int
    chunk_count: int
    total_queries: int
    average_latency_ms: float

class IngestTaskResponse(BaseModel):
    id: str
    file_name: str
    stage: str
    progress: int = 0
    error_msg: Optional[str] = None
    started_at: Optional[datetime] = None
