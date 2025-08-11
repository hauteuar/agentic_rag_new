
import os, io, uuid, time, json, re
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from storage import DB, ensure_dirs
from ingest import TextIngestor
from code_ingest import CodeIngestor
from retriever import VectorStore
from agent import AgenticRAG
from guardrails import redact_for_logs

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "./data")
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "rag.sqlite"))
INDEX_PATH = os.getenv("INDEX_PATH", os.path.join(DATA_DIR, "index.faiss"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "180"))

ensure_dirs(DATA_DIR)
db = DB(DB_PATH)
vector = VectorStore(INDEX_PATH)
ingestor = TextIngestor(db, vector, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
code_ingestor = CodeIngestor(db, vector)
agent = AgenticRAG(db, vector)

app = FastAPI(title="Agentic RAG (Private Bank)")
api = APIRouter(prefix="/api")
app.mount("/public", StaticFiles(directory="public", html=True), name="public")
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SessionCreate(BaseModel):
    session_name: Optional[str] = None

class ChatTurn(BaseModel):
    session_id: str
    message: str

@api.post("/session/create")
def create_session(payload: SessionCreate):
    sid = db.create_session(payload.session_name or f"Session-{uuid.uuid4().hex[:8]}")
    return {"session_id": sid}

@api.get("/session/list")
def list_sessions():
    return {"sessions": db.list_sessions()}

@api.post("/upload")
def upload_files(session_id: str = Form(...), files: List[UploadFile] = File(...)):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    total_chunks = 0
    docs = []
    for f in files:
        content = f.file.read()
        text = ingestor.extract_text(f.filename, content)
        n = ingestor.ingest_text(session_id, f.filename, text)
        total_chunks += n
        docs.append({"filename": f.filename, "chunks": n})
    return {"ingested_chunks": total_chunks, "details": docs}

@api.post("/chat")
def chat(payload: ChatTurn):
    if not db.session_exists(payload.session_id):
        raise HTTPException(400, "Invalid session_id")
    # Store user message
    db.add_message(payload.session_id, role="user", content=payload.message)
    # Agentic answer
    result = agent.answer(payload.session_id, payload.message)
    # Store assistant message
    db.add_message(payload.session_id, role="assistant", content=result["answer"], citations=json.dumps(result["citations"]))
    return result

@api.get("/history/{session_id}")

@api.post("/db2/import-table")
def db2_import_table(session_id: str = Form(...), table: str = Form(...), schema: str | None = Form(None), limit: int | None = Form(None)):
    from db2_hooks import fetch_all
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    rows = list(fetch_all(table=table, schema=schema, limit=limit))
    if not rows:
        return {"ingested_chunks": 0, "rows": 0}
    # Flatten rows to text lines to index; also store into chunks
    texts, metas = [], []
    for i, row in enumerate(rows):
        text = "\n".join(f"{k}: {v}" for k, v in row.items())
        cid = db.add_chunk(session_id, f"DB2:{schema+'.' if schema else ''}{table}", i, text)
        texts.append(text)
        metas.append({"chunk_id": cid, "session_id": session_id, "filename": f"DB2:{schema+'.' if schema else ''}{table}", "text": text, "kind": "db2"})
    vector.add_texts(texts, metas)
    return {"ingested_chunks": len(texts), "rows": len(rows)}

@api.post("/code/summarize")
def code_summarize(session_id: str = Form(...), files: list[UploadFile] | None = File(None), prompt: str = Form("Summarize the mainframe code: entry points, files/tables used, key business rules, side effects, and outputs.")):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    # If files provided, ingest them as code; else summarize code chunks already in session
    new_chunks = 0
    if files:
        for f in files:
            content = f.file.read()
            try:
                text = content.decode("utf-8", errors="ignore")
            except Exception:
                text = content.decode("latin-1", errors="ignore")
            new_chunks += code_ingestor.ingest_code(session_id, f.filename, text)
    # Build a focused query and run agent synthesis over top code chunks
    from agent import AgenticRAG
    rag = AgenticRAG(db, vector)
    question = f"{prompt}\nFocus only on code in this session. Produce a structured summary with sections for Programs/Entries, Data I/O, File/DB2 Access, Copybooks, and Notable Conditions."
    result = rag.answer(session_id, question)
    return result


def history(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    return {"history": db.get_messages(session_id)}


from csv_diff import read_csv_bytes, fetch_db2_sample, schema_diff, data_diff_on_key
from lineage import analyze_session as lineage_analyze
from field_lineage import analyze_fields
from pydantic import BaseModel

class CsvDiffResult(BaseModel):
    schema_diff: dict   # was `schema`
    data_diff: dict  

# app.py
@api.post("/db2/csv-diff", response_model=CsvDiffResult)
def db2_csv_diff(
    session_id: str = Form(...),
    table: str = Form(...),
    db2_schema: str | None = Form(None),     # <— new, safer name
    schema: str | None = Form(None),         # <— backward-compat (optional)
    key_cols: str = Form(""),
    csv_file: UploadFile = File(...),
    sample_mismatches: int = Form(20),
    db2_limit: int = Form(2000),
):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")

    # prefer db2_schema; fall back to schema; fall back to CURRENT SCHEMA
    eff_schema = db2_schema or schema or current_schema()

    csv_b = csv_file.file.read()
    df_csv = read_csv_bytes(csv_b)
    df_db2 = fetch_db2_sample(table, eff_schema, limit=db2_limit)

    sdiff = schema_diff(df_db2, df_csv)
    keys_list = [c.strip() for c in (key_cols or "").split(",") if c.strip()] or suggest_keys(df_db2, df_csv)
    ddiff = data_diff_on_key(df_db2, df_csv, keys_list, sample=sample_mismatches)

    db.add_message(session_id, role="system",
                   content=f"DB2/CSV diff on {eff_schema}.{table} keys={keys_list}")

    return {"schema_diff": sdiff, "data_diff": ddiff}

@api.get("/analysis/lineage/{session_id}")
def analysis_lineage(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    report = lineage_analyze(db, session_id)
    return {"lineage": report}

@api.get("/analysis/crud-map/{session_id}")
def analysis_crud_map(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    report = lineage_analyze(db, session_id)
    return {"crud_map": report}


from fastapi.responses import FileResponse
from lineage import analyze_session as lineage_analyze
from field_lineage import analyze_fields
from graph_builder import build_crud_graph, neighborhood_subgraph, to_pyvis_html
from export_utils import export_markdown

@api.get("/analysis/graph/crud/{session_id}")
def graph_crud(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    lineage = lineage_analyze(db, session_id)["lineage"] if "lineage" in lineage_analyze(db, session_id) else lineage_analyze(db, session_id)
    G = build_crud_graph(lineage)
    out_html = os.path.join(DATA_DIR, f"{session_id}_crud_map.html")
    to_pyvis_html(G, out_html, title="CRUD Map")
    return {"html_path": out_html, "url": f"/data/{os.path.basename(out_html)}"}

@api.get("/analysis/graph/dependency/{session_id}")
def graph_dependency(session_id: str, element: str, radius: int = 2):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    lineage = lineage_analyze(db, session_id)["lineage"] if "lineage" in lineage_analyze(db, session_id) else lineage_analyze(db, session_id)
    G = build_crud_graph(lineage)
    sub = neighborhood_subgraph(G, element, radius=radius)
    out_html = os.path.join(DATA_DIR, f"{session_id}_dep_{element.replace('/','_')}.html")
    to_pyvis_html(sub, out_html, title=f"Dependency: {element}")
    return {"html_path": out_html, "url": f"/data/{os.path.basename(out_html)}"}

@api.post("/export/session")
def export_session(session_id: str = Form(...), include_llm: bool = Form(False)):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    lineage = lineage_analyze(db, session_id)
    # fetch last assistant message as synthesis if requested
    synthesis = None
    if include_llm:
        msgs = db.get_messages(session_id)
        for m in reversed(msgs):
            if m["role"] == "assistant":
                synthesis = m["content"]
                break
    md_path = export_markdown(session_id, lineage.get("lineage", lineage), synthesis, DATA_DIR)
    return {"md_path": md_path}

@api.get("/analysis/fields/{session_id}")
def analysis_fields(session_id: str, copybook: str):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    return analyze_fields(db, session_id, copybook)

@api.get("/healthz")

import zipfile, io
from code_ingest import CodeIngestor

@api.post("/batch/upload-zip")
def batch_upload_zip(session_id: str = Form(...), archive: UploadFile = File(...)):
    if not db.session_exists(session_id):
        raise HTTPException(400, "Invalid session_id")
    content = archive.file.read()
    zf = zipfile.ZipFile(io.BytesIO(content))
    count_docs = count_code = total_chunks = 0
    for name in zf.namelist():
        if name.endswith('/'): 
            continue
        data = zf.read(name)
        lname = name.lower()
        try:
            if lname.endswith(('.pdf','.docx','.txt')):
                text = ingestor.extract_text(name, data)
                n = ingestor.ingest_text(session_id, name, text)
                count_docs += 1; total_chunks += n
            elif lname.endswith(('.cbl','.cob','.cpy','.jcl','.cics','.txt')):
                # default utf-8 decode; fallback latin-1
                try:
                    code = data.decode('utf-8', errors='ignore')
                except Exception:
                    code = data.decode('latin-1', errors='ignore')
                n = code_ingestor.ingest_code(session_id, name, code)
                count_code += 1; total_chunks += n
        except Exception as e:
            # skip problematic file and continue
            pass
    return {"count_docs": count_docs, "count_code": count_code, "total_chunks": total_chunks}

def health():
    return {"status": "ok"}


app.include_router(api)

@app.get("/")
def root():
    return {"message":"OK. Open /public/ for UI."}
