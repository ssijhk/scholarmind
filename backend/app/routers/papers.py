"""Papers and folders router — MySQL-backed CRUD."""
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import List
from datetime import datetime
from sqlalchemy import text
from redis import Redis
from rq import Queue
from app.schemas.papers import FolderCreate, FolderResponse, PaperResponse, PaperUploadResponse, PaperDetailResponse
from common.auth.deps import get_current_user_id
from common.db.mysql import AsyncSessionLocal
from common.db.minio_client import minio_client
from common.config import settings
from common.logging import logger
import xxhash

router = APIRouter(prefix="/papers", tags=["papers"])
folders_router = APIRouter(prefix="/folders", tags=["folders"])


# ─── Folders ────────────────────────────────────────────────────────────────

@folders_router.post("/", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(data: FolderCreate, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        fid = str(uuid.uuid4())[:12]
        await session.execute(
            text("INSERT INTO folders (id, user_id, name, parent_id, created_at) VALUES (:id, :uid, :name, :pid, :now)"),
            {"id": fid, "uid": user_id, "name": data.name, "pid": data.parent_id or "", "now": datetime.now()},
        )
        await session.commit()
    return FolderResponse(id=fid, name=data.name, paper_count=0, created_at=datetime.now())


@folders_router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(id: str, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM folders WHERE id = :fid AND user_id = :uid"), {"fid": id, "uid": user_id})
        await session.commit()


@folders_router.get("/", response_model=List[FolderResponse])
async def list_folders(user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name, created_at FROM folders WHERE user_id = :uid ORDER BY created_at DESC"),
            {"uid": user_id},
        )
        return [
            FolderResponse(id=r[0], name=r[1], paper_count=0, created_at=r[2])
            for r in result.fetchall()
        ]


# ─── Papers ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=List[PaperUploadResponse], status_code=status.HTTP_202_ACCEPTED)
async def upload_papers(files: List[UploadFile] = File(...), user_id: str = Depends(get_current_user_id)):
    results = []
    redis_conn = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
    ingest_queue = Queue("ingest", connection=redis_conn)

    for file in files:
        pdf_bytes = await file.read()
        file_hash = xxhash.xxh64(pdf_bytes).hexdigest()
        pdf_key = f"{user_id}/{file_hash}/original.pdf"

        # Store to MinIO
        minio_client.put_object(
            settings.MINIO_BUCKET_PDF, pdf_key,
            io.BytesIO(pdf_bytes), len(pdf_bytes), "application/pdf",
        )

        # Create paper record
        pid = file_hash[:12]
        status_val = "pending"
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO papers (id, user_id, title, file_hash, pdf_key, status, created_at) "
                    "VALUES (:id, :uid, :title, :hash, :key, :status, :now) "
                    "ON DUPLICATE KEY UPDATE status=VALUES(status)"
                ),
                {"id": pid, "uid": user_id, "title": file.filename, "hash": file_hash, "key": pdf_key, "status": status_val, "now": datetime.now()},
            )
            # Also create ingest_task for observability
            await session.execute(
                text(
                    "INSERT INTO ingest_tasks (id, user_id, paper_id, file_name, file_hash, stage, progress, created_at) "
                    "VALUES (:id, :uid, :pid, :name, :hash, :stage, 0, :now)"
                ),
                {
                    "id": str(uuid.uuid4())[:12], "uid": user_id, "pid": pid,
                    "name": file.filename, "hash": file_hash, "stage": "pending", "now": datetime.now(),
                },
            )
            await session.commit()

        # Enqueue parsing task to RQ worker
        try:
            ingest_queue.enqueue(
                "services.parsing.orchestrator.ingest_paper",
                user_id, pid, pdf_key,
                job_timeout=600,
            )
            logger.info(f"Enqueued ingest task for paper {pid}")
        except Exception as e:
            logger.error(f"Failed to enqueue ingest task: {e}")

        results.append(PaperUploadResponse(
            id=pid, title=file.filename, file_hash=file_hash, status=status_val, message="Paper uploaded, pending processing"
        ))

    return results


@router.get("/", response_model=List[PaperResponse])
async def list_papers(user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, title, authors, abstract, year, status, chunk_count, created_at FROM papers WHERE user_id = :uid ORDER BY created_at DESC"),
            {"uid": user_id},
        )
        return [
            PaperResponse(id=r[0], title=r[1], authors=r[2] or "", abstract=r[3] or "", year=r[4] or 0, status=r[5], chunk_count=r[6] or 0, created_at=r[7])
            for r in result.fetchall()
        ]


@router.get("/{id}", response_model=PaperDetailResponse)
async def get_paper(id: str, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM papers WHERE id = :pid AND user_id = :uid"),
            {"pid": id, "uid": user_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Paper not found")
        r = row._mapping
    return PaperDetailResponse(id=r["id"], title=r["title"], authors=r.get("authors", ""), abstract=r.get("abstract", ""), year=r.get("year", 0), doi=r.get("doi", ""), status=r["status"], pdf_key=r.get("pdf_key", ""), chunk_count=r.get("chunk_count", 0), created_at=r["created_at"])


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(id: str, user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM papers WHERE id = :pid AND user_id = :uid"), {"pid": id, "uid": user_id})
        await session.commit()
