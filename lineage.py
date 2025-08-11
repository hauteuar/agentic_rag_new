
import re
from typing import Dict, Any, List, Tuple
from storage import DB

# Regex heuristics for COBOL/VSAM/DB2/JCL/CICS/MQ/XML
RE_FILE_ASSIGN = re.compile(r'\bSELECT\s+(\S+)\s+ASSIGN\b', re.IGNORECASE)
RE_FD = re.compile(r'\bFD\s+(\S+)', re.IGNORECASE)
RE_READ = re.compile(r'\bREAD\s+(\S+)', re.IGNORECASE)
RE_WRITE = re.compile(r'\bWRITE\s+(\S+)', re.IGNORECASE)
RE_REWRITE = re.compile(r'\bREWRITE\s+(\S+)', re.IGNORECASE)
RE_DELETE = re.compile(r'\bDELETE\s+(\S+)', re.IGNORECASE)

RE_EXEC_SQL = re.compile(r'EXEC\s+SQL(.*?)END-EXEC\.', re.IGNORECASE | re.DOTALL)
RE_SQL_TABLE = re.compile(r'\bFROM\s+([A-Z0-9_."]+)|\bINTO\s+([A-Z0-9_."]+)', re.IGNORECASE)
RE_SQL_VERB = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE)\b', re.IGNORECASE)

RE_JCL_DD = re.compile(r'^\s*//(?P<step>\S+)\s+DD\s+DSN=(?P<dsn>[^,]+)', re.IGNORECASE | re.MULTILINE)

# COPY statements (copybooks)
RE_COPY = re.compile(r'\bCOPY\s+["\']?([A-Z0-9_.\-\/]+)["\']?', re.IGNORECASE)

# CICS verbs (basic)
RE_CICS = re.compile(r'EXEC\s+CICS\s+(READ|REWRITE|WRITE|DELETE)\s+(FILE|QUEUE)\s*\(\s*([\w\-\.\']+)\s*\)', re.IGNORECASE)

# MQ calls
RE_MQ_CALL = re.compile(r'CALL\s+["\']MQ(PUT|GET|OPEN|CLOSE)["\']', re.IGNORECASE)

# XML verbs
RE_XML_GEN = re.compile(r'\bXML\s+GENERATE\b\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_XML_PARSE = re.compile(r'\bXML\s+PARSE\b\s+([A-Z0-9\-]+)', re.IGNORECASE)

# Logical <- DDNAME mapping
RE_SELECT_ASSIGN = re.compile(r'\bSELECT\s+(\S+)\s+ASSIGN\s+TO\s+([A-Z0-9_\-\'"]+)', re.IGNORECASE)

def _add_op(d: Dict[str, Any], subject: str, op: str, program: str, line: int):
    subject = subject.strip().strip('.').strip('"').strip("'")
    if subject not in d:
        d[subject] = {"ops": {}, "programs": set()}
    d[subject]["ops"][op] = d[subject]["ops"].get(op, 0) + 1
    d[subject]["programs"].add(program)

def _norm_copy_name(name: str) -> Tuple[str, str]:
    # Return (logical_name, physical_name) where physical may add .CPY if missing.
    n = name.strip().strip('"').strip("'")
    base = n.split('/')[-1]
    logical = base.split('.')[0].upper()
    physical = base if base.upper().endswith(('.CPY', '.COPYBOOK')) else (base + '.CPY')
    return (logical, physical.upper())

def analyze_session(db: DB, session_id: str) -> Dict[str, Any]:
    # Scan code chunks in a session to build CRUD map & lineage heuristics.
    lineage_files: Dict[str, Any] = {}
    lineage_tables: Dict[str, Any] = {}

    # pull all chunks from this session
    import sqlite3
    con = sqlite3.connect(db.db_path)
    cur = con.cursor()
    rows = cur.execute("SELECT filename, content FROM chunks WHERE session_id=? ORDER BY id ASC", (session_id,)).fetchall()
    con.close()

    for filename, content in rows:
        fname = (filename or "").lower()
        program = filename

        # Only scan relevant files
        if not any(x in fname for x in [".cbl",".cob",".cpy",".jcl",".cics","db2:"]):
            continue

        # VSAM/COBOL file ops
        for m in RE_FILE_ASSIGN.finditer(content):
            _add_op(lineage_files, m.group(1), "ASSIGN", program, 0)
        for m in RE_FD.finditer(content):
            _add_op(lineage_files, m.group(1), "FD", program, 0)
        for m in RE_READ.finditer(content):
            _add_op(lineage_files, m.group(1), "READ", program, 0)
        for m in RE_WRITE.finditer(content):
            _add_op(lineage_files, m.group(1), "WRITE", program, 0)
        for m in RE_REWRITE.finditer(content):
            _add_op(lineage_files, m.group(1), "REWRITE", program, 0)
        for m in RE_DELETE.finditer(content):
            _add_op(lineage_files, m.group(1), "DELETE", program, 0)

        # DB2/SQL
        for block in RE_EXEC_SQL.findall(content):
            verb = None
            vm = RE_SQL_VERB.search(block)
            if vm:
                verb = vm.group(1).upper()
            for tm in RE_SQL_TABLE.finditer(block):
                tbl = tm.group(1) or tm.group(2)
                if not tbl:
                    continue
                subj = tbl.replace('\n',' ').strip()
                if verb:
                    _add_op(lineage_tables, subj, verb, program, 0)

        # COPY usage
        for m in RE_COPY.finditer(content):
            logical, physical = _norm_copy_name(m.group(1).upper())
            _add_op(lineage_files, f"COPYBOOK:{logical}", "COPY", program, 0)
            _add_op(lineage_files, f"COPYBOOK:{physical}", "COPY", program, 0)

        # CICS
        for m in RE_CICS.finditer(content):
            obj = m.group(3).strip(" '\"")
            _add_op(lineage_files, obj, f"CICS_{m.group(1).upper()}", program, 0)

        # MQ
        for m in RE_MQ_CALL.finditer(content):
            _add_op(lineage_files, "MQ", f"MQ{m.group(1).upper()}", program, 0)

        # XML
        for m in RE_XML_GEN.finditer(content):
            _add_op(lineage_files, m.group(1), "XML_GENERATE", program, 0)
        for m in RE_XML_PARSE.finditer(content):
            _add_op(lineage_files, m.group(1), "XML_PARSE", program, 0)

        # Logical ↔ DDNAME mapping
        for m in RE_SELECT_ASSIGN.finditer(content):
            logical = m.group(1)
            ddname = m.group(2).strip("'\" ")
            _add_op(lineage_files, f"LOGICAL:{logical}", f"ASSIGN:{ddname}", program, 0)

        # JCL: DSN capture
        for jm in RE_JCL_DD.finditer(content):
            dsn = jm.group('dsn')
            _add_op(lineage_files, f"DSN:{dsn}", "JCL_DD", program, 0)

    # finalize sets
    def finalize(d: Dict[str, Any]):
        out = {}
        for k, v in d.items():
            out[k] = {"ops": v["ops"], "programs": sorted(list(v["programs"]))}
        return out

    return {"files": finalize(lineage_files), "tables": finalize(lineage_tables)}
