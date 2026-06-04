from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None

class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    paper_count: int = 0
    created_at: Optional[datetime] = None

class PaperResponse(BaseModel):
    id: str
    title: str
    authors: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    folder_id: Optional[str] = None
    status: str = "pending"
    file_key: Optional[str] = None
    file_size: Optional[int] = None
    pages: int = 0
    chunk_count: int = 0
    created_at: Optional[datetime] = None

class PaperUploadResponse(BaseModel):
    id: str
    title: str
    file_hash: str
    status: str
    message: str

class PaperDetailResponse(PaperResponse):
    doi: Optional[str] = None
    pdf_key: Optional[str] = None
    meta_data: Optional[dict] = None
