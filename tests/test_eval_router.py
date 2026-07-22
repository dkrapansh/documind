import json

def _auth_headers(client, tenant_name: str = "acme") -> dict:
    response = client.post("/auth/keys", json={"tenant_name": tenant_name})
    raw_key = response.json()["api_key"]
    return {"X-API-Key": raw_key}

def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536

class _FakeRagasResult:
    def __init__(self, scores):
        self.scores = scores

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
        ],
    }
    dataset_path = tmp_path / "golden_dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")

    monkeypatch.setattr("app.services.evaluation.GOLDEN_CORPUS_DIR", corpus_dir)
    monkeypatch.setattr("app.services.evaluation.GOLDEN_DATASET_PATH", dataset_path)
    monkeypatch.setattr("app.services.evaluation._ITEM_PACING_SECONDS", 0)

def _mock_pipeline(monkeypatch):
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

def test_post_eval_runs_then_get_returns_persisted_results(tmp_path, client, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)
    _mock_pipeline(monkeypatch)

    headers = _auth_headers(client)

    post_response = client.post("/eval/runs", headers=headers, json={})
    assert post_response.status_code == 200
    body = post_response.json()
    assert body["dataset_version"] == "test-v1"
    run_id = body["id"]

    # TestClient runs BackgroundTasks to completion before returning, so
    # the run is already done by the time GET is called here.
    get_response = client.get(f"/eval/runs/{run_id}", headers=headers)
    assert get_response.status_code == 200
    results = get_response.json()["results"]
    assert len(results) == 1
    assert results[0]["question"] == "What is the refund window?"
    assert results[0]["faithfulness"] == 0.9

def test_post_eval_runs_honors_confidence_threshold_override(tmp_path, client, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)
    _mock_pipeline(monkeypatch)

    headers = _auth_headers(client)

    post_response = client.post(
        "/eval/runs", headers=headers, json={"confidence_threshold_override": -2.0}
    )
    assert post_response.json()["config"]["confidence_threshold"] == -2.0

def test_get_eval_run_is_scoped_to_requesting_tenant(tmp_path, client, monkeypatch):
    _write_fake_golden_set(tmp_path, monkeypatch)
    _mock_pipeline(monkeypatch)

    owner_headers = _auth_headers(client, "acme")
    other_headers = _auth_headers(client, "globex")

    run_id = client.post("/eval/runs", headers=owner_headers, json={}).json()["id"]

    owner_response = client.get(f"/eval/runs/{run_id}", headers=owner_headers)
    other_response = client.get(f"/eval/runs/{run_id}", headers=other_headers)

    assert owner_response.status_code == 200
    assert other_response.status_code == 404

def test_get_unknown_eval_run_returns_404(client):
    headers = _auth_headers(client)
    response = client.get("/eval/runs/999999", headers=headers)
    assert response.status_code == 404
