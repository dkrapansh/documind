from datetime import datetime

from pydantic import BaseModel

class EvalRunRequest(BaseModel):
    confidence_threshold_override: float | None = None

class EvalResultResponse(BaseModel):
    question: str
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None

    model_config = {"from_attributes": True}

class EvalRunResponse(BaseModel):
    id: int
    dataset_version: str
    config: dict
    created_at: datetime
    results: list[EvalResultResponse]

    model_config = {"from_attributes": True}
