from fastapi.testclient import TestClient

import backend.main as main


def reset_index():
    main.DOCUMENTS.clear()
    main.CHUNKS.clear()
    main.load_seed_documents()


def test_seed_documents_are_indexed():
    reset_index()
    assert len(main.DOCUMENTS) >= 1
    assert len(main.CHUNKS) >= 1
    metrics = main.extract_dashboard_metrics()
    assert metrics["documents"] >= 1
    assert metrics["avg_growth_pct"] > 0
    assert metrics["avg_net_margin_pct"] > 0


def test_chat_endpoint_returns_answer_with_citations():
    reset_index()
    client = TestClient(main.app)
    response = client.post("/api/chat", json={"question": "What is the revenue growth?"})
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "citations" in payload
    assert payload["confidence"] in {"low", "medium", "high"}
    assert isinstance(payload["citations"], list)


def test_upload_endpoint_accepts_txt_file():
    reset_index()
    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("demo.txt", "Revenue: $50 million. Net margin: 20%. Revenue growth: 8%.", "text/plain")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["name"].startswith("demo")
