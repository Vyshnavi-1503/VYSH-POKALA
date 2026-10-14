# Financial Intelligence Agent

A lightweight financial research web app with:
- Document upload and indexing for `.txt`, `.csv`, and `.pdf` files
- Chat-based assistant grounded in retrieved evidence
- Simple financial KPI dashboard
- Cited source references from indexed documents
- Local Ollama integration for optional AI answer generation

## Run locally

```bash
cd /Users/vyshnavireddy/Downloads/VYSH\ POKALA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

Then open:
- http://127.0.0.1:8002/

## Notes
- The app automatically loads sample financial documents from `data/sample_documents`.
- If Ollama is running locally with the `qwen2.5:3b` model installed, the assistant will use it to generate grounded answers.
- If the model is unavailable, the app falls back to a retrieval-based answer using the indexed evidence.
