
import re
from typing import Dict, Any, List, Tuple, Set
import sqlite3
from storage import DB

# --- Copybook field parser (very heuristic) ---
# Matches lines like: "05  FIELD-NAME     PIC X(10) [VALUE 'ABC']."
RE_FIELD = re.compile(
    r'^\s*(?P<level>\d{2})\s+(?P<name>[A-Z0-9\-]+)'
    r'(?:\s+PIC\s+(?P<pic>[\w\(\)9XV\.\-]+))?'
    r'(?:\s+VALUE\s+(?P<value>[^.\n]+))?',
    re.IGNORECASE | re.MULTILINE
)

# Identify a 01-level record name to map WRITE/REWRITE targets
RE_RECORD01 = re.compile(r'^\s*01\s+(?P<rec>[A-Z0-9\-]+)\b', re.IGNORECASE | re.MULTILINE)

# MOVE and arithmetic patterns
RE_MOVE = re.compile(r'\bMOVE\s+([A-Z0-9\-]+)\s+TO\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_COMPUTE = re.compile(r'\bCOMPUTE\s+([A-Z0-9\-]+)\s*=', re.IGNORECASE)
RE_ADD = re.compile(r'\bADD\s+.+\s+TO\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_SUB = re.compile(r'\bSUBTRACT\s+.+\s+FROM\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_MULT = re.compile(r'\bMULTIPLY\s+.+\s+BY\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_DIV = re.compile(r'\bDIVIDE\s+.+\s+INTO\s+([A-Z0-9\-]+)', re.IGNORECASE)

# IF conditions treat fields as inputs
RE_IF = re.compile(r'\bIF\s+([^\.]+)\.', re.IGNORECASE | re.DOTALL)

# SQL host variables: :FIELD
RE_SQL_HOST = re.compile(r':([A-Z0-9_\-]+)')
RE_SQL_INSERT = re.compile(r'\bINSERT\b', re.IGNORECASE)
RE_SQL_UPDATE = re.compile(r'\bUPDATE\b', re.IGNORECASE)
RE_SQL_SELECT = re.compile(r'\bSELECT\b', re.IGNORECASE)
RE_SQL_INTO = re.compile(r'\bINTO\s+([A-Z0-9\:\,\s\-]+)', re.IGNORECASE)
RE_SQL_SET = re.compile(r'\bSET\s+([A-Z0-9\:\=\s,\-]+)', re.IGNORECASE)
RE_SQL_WHERE = re.compile(r'\bWHERE\s+([A-Z0-9\:\s=\<\>\,\-\+\*\/\(\)]+)', re.IGNORECASE)

RE_WRITE = re.compile(r'\bWRITE\s+([A-Z0-9\-]+)', re.IGNORECASE)
RE_REWRITE = re.compile(r'\bREWRITE\s+([A-Z0-9\-]+)', re.IGNORECASE)

def _collect_copybook_fields(text: str) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    rec = None
    m = RE_RECORD01.search(text)
    if m:
        rec = m.group('rec').upper()
    fields = {}
    for fm in RE_FIELD.finditer(text):
        name = fm.group('name').upper()
        level = int(fm.group('level'))
        pic = (fm.group('pic') or '').upper()
        val = (fm.group('value') or '').strip()
        fields[name] = {"level": level, "pic": pic, "value": val, "static": bool(val)}
    return rec, fields

def _wordset(s: str) -> Set[str]:
    return set(re.findall(r'\b[A-Z][A-Z0-9\-]+\b', s.upper()))

def analyze_fields(db: DB, session_id: str, copybook_hint: str) -> Dict[str, Any]:
    cb_hint = (copybook_hint or "").upper()
    # Load all chunks for session
    con = sqlite3.connect(db.db_path)
    cur = con.cursor()
    rows = cur.execute("SELECT filename, content FROM chunks WHERE session_id=? ORDER BY id ASC", (session_id,)).fetchall()
    con.close()

    # Find copybook chunk(s)
    cb_texts = []
    for fn, content in rows:
        low = (fn or "").lower()
        if ".cpy" in low or ".copybook" in low or "copybook:" in (fn or "").upper():
            if cb_hint and cb_hint not in fn.upper() and cb_hint not in content.upper():
                continue
            cb_texts.append((fn, content))

    if not cb_texts:
        return {"error": "No copybook content found for hint", "hint": cb_hint}

    # For now, merge copybook fields across all matches
    record_names = set()
    fields = {}
    for fn, text in cb_texts:
        rec, fdict = _collect_copybook_fields(text)
        if rec: record_names.add(rec)
        for k, v in fdict.items():
            fields.setdefault(k, v)

    # Initialize usage buckets
    input_use: Set[str] = set()
    updated_use: Set[str] = set()
    static_fields: Set[str] = set(k for k, v in fields.items() if v.get("static"))
    referenced: Set[str] = set()

    # Scan program chunks for references
    for fn, content in rows:
        u = content.upper()
        words = _wordset(u)

        # Only consider fields from this copybook (by name presence)
        candidate_words = words.intersection(set(fields.keys()))

        # IF conditions -> input
        for im in RE_IF.finditer(u):
            cond = im.group(1)
            cond_words = _wordset(cond)
            input_use.update(cond_words.intersection(candidate_words))

        # MOVE
        for mm in RE_MOVE.finditer(u):
            src, dest = mm.group(1).upper(), mm.group(2).upper()
            if src in fields: input_use.add(src)
            if dest in fields: updated_use.add(dest)

        # COMPUTE/ADD/SUB/MULT/DIV
        for cm in RE_COMPUTE.finditer(u):
            dest = cm.group(1).upper()
            if dest in fields: updated_use.add(dest)
        for am in RE_ADD.finditer(u):
            dest = am.group(1).upper()
            if dest in fields: updated_use.add(dest)
        for sm in RE_SUB.finditer(u):
            dest = sm.group(1).upper()
            if dest in fields: updated_use.add(dest)
        for mm in RE_MULT.finditer(u):
            dest = mm.group(1).upper()
            if dest in fields: updated_use.add(dest)
        for dm in RE_DIV.finditer(u):
            dest = dm.group(1).upper()
            if dest in fields: updated_use.add(dest)

        # EXEC SQL blocks: host variables
        for block in re.findall(r'EXEC\s+SQL(.*?)END-EXEC\.', u, flags=re.IGNORECASE | re.DOTALL):
            # INSERT/UPDATE -> treat host vars as input to DB2 (values written)
            if RE_SQL_INSERT.search(block) or RE_SQL_UPDATE.search(block):
                # SET clause host variables
                setm = RE_SQL_SET.search(block)
                if setm:
                    for hv in RE_SQL_HOST.findall(setm.group(1)):
                        hvu = hv.upper()
                        if hvu in fields: input_use.add(hvu)
                # VALUES/host vars
                for hv in RE_SQL_HOST.findall(block):
                    hvu = hv.upper()
                    if hvu in fields: input_use.add(hvu)
            # SELECT INTO -> treat host vars in INTO as updated (receivers)
            if RE_SQL_SELECT.search(block):
                for inm in RE_SQL_INTO.finditer(block):
                    for hv in RE_SQL_HOST.findall(inm.group(1)):
                        hvu = hv.upper()
                        if hvu in fields: updated_use.add(hvu)
                # WHERE host vars -> input
                wm = RE_SQL_WHERE.search(block)
                if wm:
                    for hv in RE_SQL_HOST.findall(wm.group(1)):
                        hvu = hv.upper()
                        if hvu in fields: input_use.add(hvu)

        # Record-level WRITE/REWRITE
        for wr in RE_WRITE.finditer(u):
            rec = wr.group(1).upper()
            if rec in record_names:
                updated_use.update(fields.keys())
        for rw in RE_REWRITE.finditer(u):
            rec = rw.group(1).upper()
            if rec in record_names:
                updated_use.update(fields.keys())

        referenced.update(candidate_words)

    # Compute categories
    used = input_use.union(updated_use)
    unused = set(fields.keys()) - used
    # static that are also used: keep them in static but they might appear in input/updated too; for the high-level buckets we list them separately
    result = {
        "copybook_hint": cb_hint,
        "record_names": sorted(list(record_names)),
        "totals": {
            "fields": len(fields),
            "input": len(input_use),
            "derived_or_updated": len(updated_use),
            "static": len(static_fields),
            "unused": len(unused),
        },
        "fields": {
            "input": sorted(list(input_use)),
            "derived_or_updated": sorted(list(updated_use)),
            "static": sorted(list(static_fields)),
            "unused": sorted(list(unused)),
        },
        "field_meta": fields,
    }
    return result
