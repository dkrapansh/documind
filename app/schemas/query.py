from datetime import datetime

from pydantic import BaseModel, Field

# A multi-MB question would still get embedded (a paid Gemini call) and
# BM25-tokenized over the tenant's whole corpus before anything rejects
# it, so this bounds it at the API boundary. 2000 chars is generous for
# any real question, including the multi-part ones in the golden dataset.
MAX_QUESTION_LENGTH = 2000

class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str | None = None

class RetrievedChunk(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    distance: float | None = None
    confidence: float | None = None

    model_config = {"from_attributes": True}

class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[RetrievedChunk]
    session_id: str | None = None

class BM25Chunk(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    score: float

class FusedChunk(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    rrf_score: float

class QueryLogResponse(BaseModel):
    question: str
    answer: str
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}