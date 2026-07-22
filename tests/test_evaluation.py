import json

from app.repositories.eval_runs import list_eval_results
from app.repositories.tenants import create_tenant
from app.services.evaluation import run_evaluation

def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536

def _requesting_tenant_id(db_session) -> int:
    return create_tenant(db_session, name="requester").id

def _write_fake_golden_set(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "golden_corpus"
    corpus_dir.mkdir()
    (corpus_dir / "refund.txt").write_text(
        "Refunds are available within 30 days of purchase.", encoding="utf-8"
    )

    dataset = {
        "version": "test-v1",
        "items": [
            {
                "id": "t-001",
                "question": "What is the refund window?",
                "ground_truth": "Refunds are available within 30 days of purchase.",
                "reference_contexts": ["Refunds are available within 30 days of purchase."],
                "source_documents": ["refund.txt"],
                "category": "single_chunk_lookup",
            },
            {
                "id": "t-002",
                "question": "Do you offer a white-label plan?",
                "ground_truth": "Not offered.",
                "reference_contexts": [],
                "source_documents": [],
                "category": "expected_refusal",
            },
        ],
    }
    dataset_path = tmp_path / "golden_dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")

    monkeypatch.setattr("app.services.evaluation.GOLDEN_CORPUS_DIR", corpus_dir)
    monkeypatch.setattr("app.services.evaluation.GOLDEN_DATASET_PATH", dataset_path)
    # Real free-tier rate-limit pacing has nothing to protect against
    # here - generate_answer/embed_text are mocked, not hitting Gemini.
    monkeypatch.setattr("app.services.evaluation._ITEM_PACING_SECONDS", 0)

class _FakeRagasResult:
    def __init__(self, scores):
        self.scores = scores

def test_run_evaluation_scores_answered_items_and_skips_refusals(tmp_path, db_session, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)

    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    monkeypatch.setattr(
        "app.services.answering.generate_answer",
        lambda messages: "Refunds are available within 30 days of purchase.",
    )

    captured = {}
    def _fake_evaluate(dataset, metrics, llm, embeddings, run_config):
        captured["rows"] = dataset.to_list()
        return _FakeRagasResult([
            {"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 1.0}
        ])
    monkeypatch.setattr("app.services.evaluation.evaluate", _fake_evaluate)

    eval_run = run_evaluation(db_session, requesting_tenant_id=_requesting_tenant_id(db_session))

    # Only the single_chunk_lookup item should have been sent to RAGAS -
    # the expected_refusal item has no retrievable context to score.
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["user_input"] == "What is the refund window?"

    results = list_eval_results(db_session, eval_run.id)
    assert len(results) == 2

    scored = next(r for r in results if r.question == "What is the refund window?")
    assert scored.faithfulness == 0.9
    assert scored.answer_relevancy == 0.8
    assert scored.context_precision == 1.0

    refused = next(r for r in results if r.question == "Do you offer a white-label plan?")
    assert refused.faithfulness is None
    assert refused.answer_relevancy is None
    assert refused.context_precision is None

def test_run_evaluation_reuses_the_same_eval_tenant_across_runs(tmp_path, db_session, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)

    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    monkeypatch.setattr(
        "app.services.answering.generate_answer",
        lambda messages: "Refunds are available within 30 days of purchase.",
    )
    monkeypatch.setattr(
        "app.services.evaluation.evaluate",
        lambda dataset, metrics, llm, embeddings, run_config: _FakeRagasResult(
            [{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 1.0}]
        ),
    )

    from app.models.document import Document

    tenant_id = _requesting_tenant_id(db_session)
    run_evaluation(db_session, requesting_tenant_id=tenant_id)
    run_evaluation(db_session, requesting_tenant_id=tenant_id)

    # Content-hash dedup on the same eval tenant means the second run must
    # not re-ingest (and re-embed) the golden corpus from scratch.
    documents = db_session.query(Document).all()
    assert len(documents) == 1

def test_run_evaluation_uses_the_confidence_threshold_override(tmp_path, db_session, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)

    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    monkeypatch.setattr(
        "app.services.answering.generate_answer",
        lambda messages: "Refunds are available within 30 days of purchase.",
    )
    monkeypatch.setattr(
        "app.services.evaluation.evaluate",
        lambda dataset, metrics, llm, embeddings, run_config: _FakeRagasResult(
            [{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 1.0}]
        ),
    )

    eval_run = run_evaluation(
        db_session,
        requesting_tenant_id=_requesting_tenant_id(db_session),
        confidence_threshold_override=-3.5,
    )

    assert eval_run.config["confidence_threshold"] == -3.5
