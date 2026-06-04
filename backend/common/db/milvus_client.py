"""Milvus client wrapper for vector store operations."""
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
from common.config import settings


def get_milvus_client():
    """Get or create Milvus connection (lazy singleton)."""
    if not connections.has_connection("default"):
        connections.connect(
            alias="default",
            uri=settings.MILVUS_URI,
            token=settings.MILVUS_TOKEN or None,
        )
    return connections


def ensure_collection() -> Collection:
    """Ensure the chunk collection exists with HNSW index and partition key."""
    get_milvus_client()
    collection_name = settings.MILVUS_COLLECTION

    if utility.has_collection(collection_name):
        col = Collection(collection_name)
        col.load()
        return col

    # Define schema
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="dense_vec", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64, is_partition_key=True),
        FieldSchema(name="paper_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="folder_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="content_en", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="content_zh", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="page_num", dtype=DataType.INT32),
        FieldSchema(name="block_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="image_key", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="sentences_en", dtype=DataType.VARCHAR, max_length=16384),
        FieldSchema(name="keywords_en", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="summary_zh", dtype=DataType.VARCHAR, max_length=4096),
    ]

    schema = CollectionSchema(fields=fields, description="ScholarMind chunks collection")
    col = Collection(name=collection_name, schema=schema)

    # Build HNSW index on dense vector
    dense_index_params = {
        "index_type": settings.MILVUS_INDEX_TYPE,
        "metric_type": settings.MILVUS_METRIC,
        "params": {"M": 16, "efConstruction": 200},
    }
    col.create_index(field_name="dense_vec", index_params=dense_index_params)

    col.load()
    return col
