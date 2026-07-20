from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str

class RetrievedChunk(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    distance: float

    model_config = {"from_attrubutes": True}

class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[RetrievedChunk]

class BM25Chunk(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    score: float