"""MinIO client for PDF and figure storage."""
from minio import Minio
from common.config import settings

minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def ensure_buckets():
    """Ensure required buckets exist."""
    for bucket in [settings.MINIO_BUCKET_PDF, settings.MINIO_BUCKET_FIG]:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
