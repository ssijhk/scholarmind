"""File serving — serve figures and PDFs from MinIO."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from common.db.minio_client import minio_client
from common.config import settings
from common.auth.deps import get_current_user_id

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/figures/{image_key:path}")
async def get_figure(image_key: str, _user_id: str = Depends(get_current_user_id)):
    """Serve a figure image from MinIO."""
    try:
        obj = minio_client.get_object(settings.MINIO_BUCKET_FIG, image_key)
        return StreamingResponse(
            obj.stream(8192),
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename={image_key.split('/')[-1]}"},
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Figure not found")
