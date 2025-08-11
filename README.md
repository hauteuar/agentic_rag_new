
# Agentic RAG (FastAPI + Streamlit) — Private Bank Ready

An on-prem Agentic RAG reference app that calls an **LLM via HTTP API** (vLLM, OpenAI-compatible, etc.),
ingests internal documents, stores embeddings locally (FAISS), and provides a secure chat UI.

## Features
- **Agentic loop**: plan → retrieve (iterative) → synthesize → cite.
- **LLM calls via API** (no SDK lock-in). Works with vLLM/OpenAI-compatible endpoints.
- **Local vector store (FAISS)**; metadata in **SQLite**.
- **Document upload**: PDF, TXT, DOCX (text extraction for PDF/DOCX via pure Python libs).
- **Session-based chat** with history, citations, and guardrails (PII redaction patterns).
- **Audit logging** for regulated environments.

> This is a starter kit — harden to your bank's standards (authN/Z, network egress controls, full DLP, etc.).

## Quickstart

### 0) Python env
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 1) Configure env
Create `.env` at repo root:
```
LLM_BASE_URL=http://localhost:8001/v1
LLM_API_KEY=changeme
LLM_MODEL=gpt-4o-mini  # or your vLLM-deployed model id
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
DATA_DIR=./data
DB_PATH=./data/rag.sqlite
INDEX_PATH=./data/index.faiss
CHUNK_SIZE=1200
CHUNK_OVERLAP=180
```

> If air-gapped, pre-download embedding model to a local path and set `EMBED_MODEL=/models/all-MiniLM-L6-v2`.

### 2) Run backend (FastAPI)
```bash
uvicorn app:app --host 0.0.0.0 --port 5173 --reload
```

### 3) Run chat UI (Streamlit)
```bash
streamlit run chat_ui.py --server.port 5174
```

### 4) Use
- Open the Streamlit UI → create or select a session → upload docs → chat.
- Backend OpenAPI docs: `http://localhost:5173/docs`.

## Security notes
- Add your IAM / SSO middleware (e.g., OAuth2/JWT) in `app.py`.
- Network egress should be restricted; LLM API should point to an internal inference server.
- Extend PII redaction before logging in `guardrails.py`.
- Use your bank's secrets manager instead of `.env` in production.



---

## DB2 Hooks

Configure `.env`:

```
# Either provide a full URL:
DB2_URL=ibm_db_sa://db2user:db2pass@db2host:50000/SAMPLE
# or parts:
DB2_HOST=your-host
DB2_PORT=50000
DB2_DB=SAMPLE
DB2_UID=db2user
DB2_PWD=db2pass
```

Then in the UI → **DB2 Import** tab → enter schema/table, optionally limit rows → **Import Table**.

Rows are flattened and indexed into FAISS so you can ask questions like _"Show large transactions over $10k in the last month and which COBOL programs reference that table."_

> Note: `ibm-db` wheel may require GCC/libdb2 runtime in your environment. Use your bank's standard DB2 client image if needed.

## Mainframe Code Summarizer

Use the **Code Summarizer** tab to upload `.cbl/.cob/.cpy/.jcl/.cics` files or summarize already-ingested code.
The system chunks code with line numbers and asks the LLM for a structured summary (Programs/Entries, Data I/O, File/DB2 Access, Copybooks, Notable Conditions).

You can tailor the prompt as needed (e.g., ask for field lineage, VSAM/DB2 CRUD map, exception paths).


## Air-gapped operation
Set these in `.env` (ensure models exist locally):
```
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
SENTENCE_TRANSFORMERS_HOME=./models
EMBED_MODEL=./models/all-MiniLM-L6-v2   # local path to embedding model
```
Point `LLM_BASE_URL` to your **internal** inference server (vLLM/OpenAI-compatible). No external calls required.

## DB2 ↔ CSV Diff
- Endpoint: `POST /db2/csv-diff`
- UI tab: **DB2 ↔ CSV Diff**
- Upload a CSV and provide DB2 table/schema + key columns
- Returns schema differences and sampled row-level mismatches

## Lineage / CRUD Maps
- Endpoints: `GET /analysis/lineage/{session_id}` and `GET /analysis/crud-map/{session_id}`
- Heuristic parsing of COBOL/COPYBOOK/JCL/SQL to map Files/VSAM and DB2 tables to operations and programs.


## Graph visualizations
- **Graphs tab** builds a full CRUD map and a dependency subgraph for a given element (program/file/table).
- Uses `networkx` + `pyvis` to render interactive HTML saved under `DATA_DIR`.
- Dependency map radius controls how far to expand neighbors around the element.

## Export
- **Export tab** creates a Markdown report combining CRUD/lineage and (optionally) the last LLM synthesis.
- The file is saved under `DATA_DIR/exports` and offered as a download.


## Standalone Web UI
- Served at **/public/** (static HTML+JS). Configure the API base at the top-right.
- Endpoints are exposed under **/api/** via the FastAPI router.
- Use this for end users; the Streamlit app remains for backend/ops.

## Batch Upload (ZIP)
- Endpoint: `POST /api/batch/upload-zip` with form fields:
  - `session_id`
  - `archive` (a `.zip` containing PDFs, DOCX, TXT, COBOL `.cbl/.cob/.cpy`, JCL `.jcl`, CICS `.cics`)
- The server extracts, ingests, and indexes all supported files recursively.


## Field Usage Analysis
Endpoint: `GET /api/analysis/fields/{session_id}?copybook=RAU`
- Parses copybook fields (levels, PIC, VALUE).
- Scans session code to classify fields as:
  - **input** (used in conditions, RHS of MOVE, WHERE host vars, etc.)
  - **derived_or_updated** (LHS of MOVE/COMPUTE, SELECT INTO receivers, WRITE/REWRITE record)
  - **static** (VALUE clause present in copybook)
  - **unused** (declared but not referenced)
- Exposed in the web UI under **Field Usage**.
