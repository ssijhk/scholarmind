from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from common.config import settings
from common.logging import logger

from app.routers.auth import router as auth_router
from app.routers.papers import router as papers_router, folders_router
from app.routers.ingest import router as ingest_router
from app.routers.chat import router as chat_router
from app.routers.advanced import router as advanced_router
from app.routers.observability import router as observability_router
from app.routers.settings import router as settings_router
from app.routers.files import router as files_router

app = FastAPI(
    title="ScholarMind API",
    description="ScholarMind (文渊) - 跨语言学术文献智能调研系统后端 API",
    version="1.0.0"
)

# Set up CORS — use explicit origins because allow_credentials=True conflicts with "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler that ensures CORS headers are present on errors."""
    logger.error(f"Unhandled error on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


# Register routers under /api prefix
app.include_router(auth_router, prefix="/api")
app.include_router(papers_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(advanced_router, prefix="/api")
app.include_router(observability_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(files_router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """Ensure MinIO buckets exist on startup."""
    from common.db.minio_client import minio_client
    for bucket in [settings.MINIO_BUCKET_PDF, settings.MINIO_BUCKET_FIG]:
        try:
            if not minio_client.bucket_exists(bucket):
                minio_client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
        except Exception as e:
            logger.error(f"Failed to create MinIO bucket {bucket}: {e}")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "scholarmind",
        "env": settings.APP_ENV
    }

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.APP_PORT, reload=True)
