
import os, requests, streamlit as st
from dotenv import load_dotenv
load_dotenv()

API_BASE = os.getenv("API_BASE", "http://localhost:5173")

st.set_page_config(page_title="Agentic RAG — Private Bank", page_icon="💼")

st.title("💼 Agentic RAG — Private Bank")
tabs = st.tabs(["Chat", "DB2 Import", "Code Summarizer", "DB2 ↔ CSV Diff", "Lineage / CRUD Maps", "Graphs", "Export"])

# Sidebar: session management
st.sidebar.header("Session")
if "session_id" not in st.session_state:
    # create on first load
    r = requests.post(f"{API_BASE}/session/create", json={"session_name": None}, timeout=30)
    st.session_state["session_id"] = r.json()["session_id"]

sid = st.text_input("Session ID", value=st.session_state["session_id"])
if st.button("New Session"):
    r = requests.post(f"{API_BASE}/session/create", json={"session_name": None}, timeout=30)
    sid = r.json()["session_id"]
    st.session_state["session_id"] = sid
    st.experimental_rerun()

st.sidebar.write(f"Active: `{sid}`")

with tabs[0]:
    st.header("Upload Documents")
uploaded = st.file_uploader("Upload PDF/DOCX/TXT", type=["pdf","docx","txt"], accept_multiple_files=True)
if uploaded and st.button("Ingest"):
    files = [("files", (f.name, f.read(), f.type or "application/octet-stream")) for f in uploaded]
    data = {"session_id": sid}
    r = requests.post(f"{API_BASE}/upload", files=files, data=data, timeout=600)
    st.success(r.json())

    st.header("Chat")
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Load previous
hr = requests.get(f"{API_BASE}/history/{sid}", timeout=30)
history = hr.json().get("history", [])
for m in history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant" and m.get("citations"):
            st.caption(f"Citations: {m['citations']}")

    user_input = st.chat_input("Ask about your internal documents…")
    if user_input:
        with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state["messages"].append({"role":"user","content":user_input})
    r = requests.post(f"{API_BASE}/chat", json={"session_id": sid, "message": user_input}, timeout=120)
    data = r.json()
            with st.chat_message("assistant"):
            st.markdown(data["answer"])
        st.caption(f"Citations: {data['citations']}")


with tabs[1]:
    st.header("DB2 Import")
    st.caption("Import a DB2 table into this session and index rows for RAG. Configure DB2 in `.env`.")
    schema = st.text_input("Schema (optional)", value="")
    table = st.text_input("Table name", value="")
    limit = st.number_input("Limit rows (optional)", min_value=0, value=0, step=100)
    if st.button("Import Table"):
        data = {"session_id": sid, "table": table, "schema": schema or None}
        if limit and int(limit) > 0:
            data["limit"] = int(limit)
        r = requests.post(f"{API_BASE}/db2/import-table", data=data, timeout=600)
        st.success(r.json())


with tabs[2]:
    st.header("Mainframe Code Summarizer")
    st.caption("Upload COBOL/COPYBOOK/JCL/CICS files or summarize code already ingested in this session.")
    files = st.file_uploader("Upload code files", type=["cbl","cob","cpy","jcl","cics","txt"], accept_multiple_files=True)
    prompt = st.text_area("Summary prompt", value="Summarize the mainframe code: entry points, files/tables used, key business rules, side effects, and outputs.")
    if st.button("Summarize Code"):
        m = {"session_id": sid, "prompt": prompt}
        if files:
            multi = [("files", (f.name, f.read(), "text/plain")) for f in files]
            r = requests.post(f"{API_BASE}/code/summarize", data=m, files=multi, timeout=600)
        else:
            r = requests.post(f"{API_BASE}/code/summarize", data=m, timeout=600)
        data = r.json()
        st.subheader("Summary")
        st.markdown(data.get("answer","(no answer)"))
        st.caption(f"Citations: {data.get('citations')}")

with tabs[3]:
    st.header("DB2 ↔ CSV Diff")
    st.caption("Compare DB2 table schema/data with a CSV file (air-gapped).")
    schema_name = st.text_input("Schema (optional)", value="")
    table_name = st.text_input("DB2 Table", value="")
    key_cols = st.text_input("Key columns (comma-separated)", value="ID")
    db2_limit = st.number_input("DB2 sample rows (for performance)", min_value=100, value=2000, step=100)
    sample_mismatches = st.number_input("Sample mismatches to show", min_value=5, value=20, step=5)
    csv_upload = st.file_uploader("Upload CSV", type=["csv"])
    if st.button("Run Diff"):
        if not csv_upload or not table_name or not key_cols.strip():
            st.error("CSV, table and key columns are required.")
        else:
            data = {
                "session_id": sid,
                "table": table_name,
                "schema": schema_name or None,
                "key_cols": key_cols,
                "sample_mismatches": int(sample_mismatches),
                "db2_limit": int(db2_limit),
            }
            files = {"csv_file": (csv_upload.name, csv_upload.getvalue(), "text/csv")}
            r = requests.post(f"{API_BASE}/db2/csv-diff", data=data, files=files, timeout=600)
            res = r.json()
            st.subheader("Schema Diff")
            st.json(res.get("schema", {}))
            st.subheader("Data Diff (sample)")
            st.json(res.get("data", {}))

with tabs[4]:
    st.header("Lineage / CRUD Maps")
    st.caption("Generate heuristic CRUD maps (VSAM/COBOL/DB2) and file lineage from ingested code.")
    if st.button("Analyze Lineage"):
        r = requests.get(f"{API_BASE}/analysis/lineage/{sid}", timeout=600)
        st.subheader("Lineage")
        st.json(r.json())
    if st.button("Generate CRUD Map"):
        r = requests.get(f"{API_BASE}/analysis/crud-map/{sid}", timeout=600)
        st.subheader("CRUD Map")
        st.json(r.json())

with tabs[5]:
    st.header("Graphs")
    st.caption("Render interactive CRUD maps and dependency subgraphs (pyvis).")
    if st.button("Build CRUD Graph"):
        r = requests.get(f"{API_BASE}/analysis/graph/crud/{sid}", timeout=600)
        path = r.json().get("html_path")
        if path:
            st.success(f"Graph generated: {path}")
            try:
                from streamlit.components.v1 import html
                html(open(path, "r", encoding="utf-8").read(), height=760)
            except Exception:
                st.info("If not visible inline, open the file from the server path.")
    element = st.text_input("Element for dependency map (program/file/table name)", value="")
    radius = st.number_input("Radius", min_value=1, value=2, step=1)
    if st.button("Build Dependency Graph"):
        if not element.strip():
            st.error("Enter an element name (e.g., ACCT_FILE, PGM::MYPROG, TABLE::BANK.ACCOUNTS)")
        else:
            r = requests.get(f"{API_BASE}/analysis/graph/dependency/{sid}", params={"element": element, "radius": int(radius)}, timeout=600)
            path = r.json().get("html_path")
            if path:
                st.success(f"Dependency graph: {path}")
                try:
                    from streamlit.components.v1 import html
                    html(open(path, "r", encoding="utf-8").read(), height=760)
                except Exception:
                    st.info("If not visible inline, open the file from the server path.")

with tabs[6]:
    st.header("Export")
    st.caption("Export analysis as Markdown (and download).")
    include_llm = st.checkbox("Include last LLM synthesis from Chat", value=True)
    if st.button("Generate Markdown"):
        r = requests.post(f"{API_BASE}/export/session", data={"session_id": sid, "include_llm": "true" if include_llm else "false"}, timeout=600)
        path = r.json().get("md_path")
        if path:
            st.success(f"Markdown generated: {path}")
            # Fetch content and enable download
            try:
                txt = open(path, "r", encoding="utf-8").read()
                st.download_button("Download Markdown", txt, file_name=path.split("/")[-1], mime="text/markdown")
            except Exception:
                st.info("Open the file from the server path if download isn't available.")
