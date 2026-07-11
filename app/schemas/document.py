from datetime import datetime
from pydantic import BaseModel

class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str
    chunk_count: int
    upload_time: datetime

    model_config = {"from_attributes": True}