from sqlalchemy.orm import Session

from app.models.query_log import QueryLog

def create_query_log(
    db: Session,
    tenant_id: int,
    session_id: str,
    question: str,
    retrieved_chunk_ids: list[int],
    answer: str,
    confidence: float | None,
    latency_ms: int,
    correlation_id: str,
) -> QueryLog:
    log = QueryLog(
        tenant_id=tenant_id,
        session_id=session_id,
        question=question,
        retrieved_chunk_ids=retrieved_chunk_ids,
        answer=answer,
        confidence=confidence,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log

def list_by_session(db: Session, tenant_id: int, session_id: str) -> list[QueryLog]:
    return (
        db.query(QueryLog)
        .filter(QueryLog.tenant_id == tenant_id, QueryLog.session_id == session_id)
        .order_by(QueryLog.created_at)
        .all()
    )
