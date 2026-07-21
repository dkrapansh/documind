from app.repositories.query_logs import create_query_log
from app.repositories.tenants import create_tenant

def test_create_query_log_persists_all_fields(db_session):
    tenant = create_tenant(db_session, "acme")

    log = create_query_log(
        db_session,
        tenant_id=tenant.id,
        session_id="session-1",
        question="What is the refund window?",
        retrieved_chunk_ids=[1, 2, 3],
        answer="30 days.",
        confidence=0.87,
        latency_ms=142,
        correlation_id="corr-1",
    )

    assert log.id is not None
    assert log.tenant_id == tenant.id
    assert log.session_id == "session-1"
    assert log.retrieved_chunk_ids == [1, 2, 3]
    assert log.confidence == 0.87
    assert log.latency_ms == 142
    assert log.correlation_id == "corr-1"
