from datetime import datetime
from pydantic import BaseModel

class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str
    chunk_count: int
    upload_time: datetime
    # Why the last ingestion attempt failed, when it did. Without this a
    # client polling a document could only ever see "failed", which cannot
    # distinguish a scanned PDF from a corrupt file from a provider outage,
    # and those need different actions from the uploader.
    error_reason: str | None = None

    model_config = {"from_attributes": True}
