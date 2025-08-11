# db2_hooks.py
import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

load_dotenv()

def _build_db2_url() -> str:
    url = (os.getenv("DB2_URL") or "").strip()
    if url:
        return url
    host = os.getenv("DB2_HOST", "").strip()
    port = os.getenv("DB2_PORT", "50000").strip()
    db   = os.getenv("DB2_DB", os.getenv("DB2_DATABASE","")).strip()
    uid  = os.getenv("DB2_UID", os.getenv("DB2_USER","")).strip()
    pwd  = os.getenv("DB2_PWD", os.getenv("DB2_PASSWORD","")).strip()
    if not (host and db and uid and pwd):
        raise ValueError("DB2 not configured. Set DB2_URL or DB2_HOST/DB2_DB(DB2_DATABASE)/DB2_UID(DB2_USER)/DB2_PWD(DB2_PASSWORD).")
    return f"ibm_db_sa://{uid}:{pwd}@{host}:{port}/{db}"

def get_engine() -> Engine:
    return create_engine(_build_db2_url(), pool_pre_ping=True)

def list_tables(schema: str | None = None):
    eng = get_engine()
    insp = inspect(eng)
    return insp.get_table_names(schema=schema)

def preview_table(table: str, schema: str | None = None, limit: int = 20):
    eng = get_engine()
    fq = f'"{schema}".{table}' if schema else table
    with eng.connect() as con:
        rows = con.execute(text(f"SELECT * FROM {fq} FETCH FIRST :n ROWS ONLY"), {"n": limit}).mappings().all()
    return [dict(r) for r in rows]

def fetch_all(table: str, schema: str | None = None, where: str | None = None, limit: int | None = None):
    eng = get_engine()
    fq = f'"{schema}".{table}' if schema else table
    sql = f"SELECT * FROM {fq}"
    if where:
        sql += f" WHERE {where}"
    if limit:
        sql += f" FETCH FIRST {int(limit)} ROWS ONLY"
    with eng.connect() as con:
        cur = con.execute(text(sql))
        cols = cur.keys()
        for row in cur:
            yield dict(zip(cols, row))

# Nice-to-haves used elsewhere
def current_schema() -> str:
    eng = get_engine()
    with eng.connect() as con:
        row = con.execute(text("SELECT CURRENT SCHEMA FROM SYSIBM.SYSDUMMY1")).fetchone()
        return (row[0] if row and row[0] else "").strip()

def table_columns(schema: str, table: str):
    eng = get_engine()
    with eng.connect() as con:
        rows = con.execute(text("""
            SELECT COLNAME, TYPENAME, LENGTH, SCALE, NULLS
            FROM SYSCAT.COLUMNS
            WHERE TABSCHEMA = :s AND TABNAME = :t
            ORDER BY COLNO
        """), {"s": schema, "t": table}).mappings().all()
    return [dict(r) for r in rows]

def table_primary_keys(schema: str, table: str):
    eng = get_engine()
    with eng.connect() as con:
        rows = con.execute(text("""
            SELECT COLNAME
            FROM SYSCAT.COLUMNS
            WHERE TABSCHEMA = :s AND TABNAME = :t AND KEYSEQ IS NOT NULL
            ORDER BY KEYSEQ
        """), {"s": schema, "t": table}).mappings().all()
    return [r["COLNAME"] for r in rows]
