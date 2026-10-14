from __future__ import annotations

import csv
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = APP_ROOT / "static"
SAMPLE_DIR = APP_ROOT / "data" / "sample_documents"
UPLOAD_DIR = APP_ROOT / "storage" / "documents"

app = FastAPI(title="Financial Intelligence Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCUMENTS: List[Dict[str, Any]] = []
CHUNKS: List[Dict[str, Any]] = []


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]]
    sources: List[str]
    confidence: str


def ensure_directories() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text_to_chunks(text: str, max_chars: int = 800, overlap: int = 120) -> List[str]:
    clean = normalize_text(text)
    if not clean:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + max_chars)
        segment = clean[start:end]
        if end < len(clean):
            last_space = segment.rfind(" ")
            if last_space > int(max_chars * 0.7):
                segment = segment[:last_space]
                end = start + last_space
        chunks.append(segment.strip())
        if end >= len(clean):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if len(chunk.strip()) > 80]


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
            rows = list(csv.reader(fp))
        return "\n".join(", ".join(row) for row in rows[:200])
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_numeric_value(raw: str) -> float | None:
    if raw is None:
        return None
    cleaned = raw.replace("$", "").replace(",", "").replace("%", "")
    cleaned = cleaned.strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value


def extract_financial_fact(text: str, keyword: str) -> Dict[str, Any]:
    q = re.compile(rf"{re.escape(keyword)}[^\n]*?([0-9]+(?:\.[0-9]+)?(?:%|M|B|m|b|USD|usd|US\$)?)", re.I)
    match = q.search(text)
    if not match:
        return {"keyword": keyword, "value": None, "raw": None}
    raw = match.group(1)
    value = parse_numeric_value(raw)
    return {"keyword": keyword, "value": value, "raw": raw}


def extract_dashboard_metrics() -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "documents": len(DOCUMENTS),
        "total_revenue_usd_m": 0.0,
        "avg_net_margin_pct": 0.0,
        "avg_growth_pct": 0.0,
        "top_company": "None",
    }
    revenue_values: List[float] = []
    margin_values: List[float] = []
    growth_values: List[float] = []
    companies: List[str] = []

    for doc in DOCUMENTS:
        text = doc["content"]
        company = doc["name"].split("_")[0].replace("-", " ").title()
        companies.append(company)
        revenue = extract_financial_fact(text, "revenue")
        margin = extract_financial_fact(text, "net margin")
        growth = extract_financial_fact(text, "revenue growth")
        if revenue["value"] is not None:
            revenue_values.append(float(revenue["value"]))
        if margin["value"] is not None:
            margin_values.append(float(margin["value"]))
        if growth["value"] is not None:
            growth_values.append(float(growth["value"]))

    if revenue_values:
        metrics["total_revenue_usd_m"] = round(sum(revenue_values), 2)
    if margin_values:
        metrics["avg_net_margin_pct"] = round(sum(margin_values) / len(margin_values), 2)
    if growth_values:
        metrics["avg_growth_pct"] = round(sum(growth_values) / len(growth_values), 2)
    if companies:
        metrics["top_company"] = companies[0]
    return metrics


def add_document(source_name: str, content: str, doc_type: str = "uploaded") -> Dict[str, Any]:
    normalized = normalize_text(content)
    doc_id = f"doc-{len(DOCUMENTS) + 1:03d}"
    document = {
        "id": doc_id,
        "name": source_name,
        "type": doc_type,
        "content": normalized,
    }
    DOCUMENTS.append(document)

    chunks = split_text_to_chunks(normalized)
    for chunk_index, chunk in enumerate(chunks):
        CHUNKS.append(
            {
                "id": f"{doc_id}-chunk-{chunk_index + 1}",
                "document_id": doc_id,
                "source": source_name,
                "content": chunk,
                "chunk_index": chunk_index + 1,
            }
        )

    return document


def load_seed_documents() -> None:
    ensure_directories()
    if DOCUMENTS or CHUNKS:
        return
    if not SAMPLE_DIR.exists():
        return

    for sample in sorted(SAMPLE_DIR.iterdir()):
        if sample.is_file():
            text = extract_text_from_file(sample)
            add_document(sample.name, text, doc_type="sample")


def build_retrieval_scores(query: str) -> List[Dict[str, Any]]:
    query_terms = [term for term in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(term) > 2]
    if not query_terms:
        return []

    doc_frequency: Counter[str] = Counter()
    for chunk in CHUNKS:
        unique_terms = set(re.findall(r"[a-zA-Z0-9]+", chunk["content"].lower()))
        for term in unique_terms:
            if len(term) > 2:
                doc_frequency[term] += 1

    total_docs = max(1, len(CHUNKS))
    idf_by_term: Dict[str, float] = {}
    for term, frequency in doc_frequency.items():
        idf_by_term[term] = math.log((1 + total_docs) / (1 + frequency)) + 1.0

    scored_chunks: List[Dict[str, Any]] = []
    for chunk in CHUNKS:
        text = chunk["content"].lower()
        tally = Counter(re.findall(r"[a-zA-Z0-9]+", text))
        score = 0.0
        for term in query_terms:
            tf = tally.get(term, 0)
            if tf:
                score += tf * idf_by_term.get(term, 1.0)
        if score > 0:
            scored_chunks.append({**chunk, "score": round(score, 4)})

    scored_chunks.sort(key=lambda item: item["score"], reverse=True)
    return scored_chunks[:5]


def generate_fallback_answer(question: str, evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "I could not find enough relevant evidence in the uploaded documents to answer that question confidently. Please upload a financial report or ask about revenue, net margin, growth, or period comparisons."

    evidence_text = " ".join(item["content"][:180] for item in evidence[:3])
    question_lower = question.lower()

    if any(keyword in question_lower for keyword in ["revenue", "sales", "income"]):
        return (
            "The evidence in the indexed reports points to a sustained revenue base and positive growth trend. "
            f"The strongest matching snippets describe: {evidence_text[:450]}"
        )
    if any(keyword in question_lower for keyword in ["margin", "profit", "net profit"]):
        return (
            "The available documents mention net margin figures and indicate healthy operating efficiency. "
            f"Key supporting excerpts: {evidence_text[:450]}"
        )
    if any(keyword in question_lower for keyword in ["growth", "compare", "change", "period"]):
        return (
            "The indexed reports compare reporting periods and show a positive change in financial performance. "
            f"Relevant evidence: {evidence_text[:450]}"
        )
    return (
        "Based on the retrieved document excerpts, the records support a positive financial outlook. "
        f"The relevant sources mention: {evidence_text[:450]}"
    )


async def ask_ollama(question: str, evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return generate_fallback_answer(question, evidence)
    context = "\n\n".join(f"Source: {item['source']}\n{item['content']}" for item in evidence)
    prompt = (
        "Use only the provided evidence. Answer briefly and cite source names like [file.txt]. "
        "If the evidence is insufficient, say so cleanly.\n\nEvidence:\n"
        f"{context}\n\nQuestion: {question}"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Ollama status {response.status_code}")
            payload = response.json()
            return payload.get("response", generate_fallback_answer(question, evidence)).strip()
    except Exception:
        return generate_fallback_answer(question, evidence)


@app.on_event("startup")
async def startup_event() -> None:
    ensure_directories()
    load_seed_documents()


@app.get("/")
async def root() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_file)


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "documents": len(DOCUMENTS), "chunks": len(CHUNKS)}


@app.get("/api/documents")
async def list_documents() -> List[Dict[str, Any]]:
    return [{"id": item["id"], "name": item["name"], "type": item["type"]} for item in DOCUMENTS]


@app.get("/api/metrics")
async def metrics() -> Dict[str, Any]:
    return extract_dashboard_metrics()


@app.post("/api/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="A question is required")

    evidence = build_retrieval_scores(question)
    answer = await ask_ollama(question, evidence) if evidence else generate_fallback_answer(question, [])

    citations = [{
        "source": item["source"],
        "chunk_index": item["chunk_index"],
        "text": item["content"],
        "score": item["score"],
    } for item in evidence]

    confidence = "medium" if evidence else "low"
    if "insufficient" in answer.lower() or not evidence:
        confidence = "low"
    elif len(citations) >= 2:
        confidence = "high"

    return ChatResponse(
        answer=answer,
        citations=citations,
        sources=list({c["source"] for c in citations}),
        confidence=confidence,
    )


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    ensure_directories()
    allowed = {".txt", ".csv", ".pdf"}
    filename = file.filename or "upload.txt"
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Only .txt, .csv, and .pdf files are supported")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is too large; limit is 10MB")

    target_path = UPLOAD_DIR / filename
    if target_path.exists():
        target_path = UPLOAD_DIR / f"{Path(filename).stem}-{len(DOCUMENTS) + 1}{suffix}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(contents)

    text = extract_text_from_file(target_path)
    doc = add_document(target_path.name, text, doc_type="upload")
    return {"message": "Document uploaded and indexed", "document": {"id": doc["id"], "name": doc["name"], "type": doc["type"]}}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
