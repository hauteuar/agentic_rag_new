
import io, os
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from sqlalchemy import text
from db2_hooks import get_engine

def _normalize_colnames(cols: List[str]) -> List[str]:
    return [c.strip().upper() for c in cols]

def read_csv_bytes(b: bytes, encoding: str = "utf-8") -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(b))
    except Exception:
        return pd.read_csv(io.BytesIO(b), encoding=encoding, engine="python")

def fetch_db2_sample(table: str, schema: Optional[str], limit: int = 2000) -> pd.DataFrame:
    eng = get_engine()
    fq = f'"{schema}".{table}' if schema else table
    with eng.connect() as con:
        df = pd.read_sql(text(f"SELECT * FROM {fq} FETCH FIRST :n ROWS ONLY"), con, params={"n": limit})
    return df

def schema_diff(db2_df: pd.DataFrame, csv_df: pd.DataFrame) -> Dict[str, Any]:
    db2_cols = _normalize_colnames(db2_df.columns.tolist())
    csv_cols = _normalize_colnames(csv_df.columns.tolist())
    set_db2, set_csv = set(db2_cols), set(csv_cols)
    return {
        "only_in_db2": sorted(list(set_db2 - set_csv)),
        "only_in_csv": sorted(list(set_csv - set_db2)),
        "common": sorted(list(set_db2 & set_csv)),
    }

def data_diff_on_key(db2_df: pd.DataFrame, csv_df: pd.DataFrame, key_cols: List[str], sample: int = 20) -> Dict[str, Any]:
    db2 = db2_df.copy()
    csv = csv_df.copy()
    db2.columns = _normalize_colnames(db2.columns.tolist())
    csv.columns = _normalize_colnames(csv.columns.tolist())
    keys = [k.upper() for k in key_cols]

    for k in keys:
        if k not in db2.columns or k not in csv.columns:
            raise ValueError(f"Key column {k} missing in one of the sources")

    db2.set_index(keys, inplace=True, drop=False)
    csv.set_index(keys, inplace=True, drop=False)

    db2_only_idx = db2.index.difference(csv.index)
    csv_only_idx = csv.index.difference(db2.index)
    both_idx = db2.index.intersection(csv.index)

    diffs = []
    common_cols = sorted(list(set(db2.columns) & set(csv.columns)))
    for idx in both_idx[:5000]:
        row_db2 = db2.loc[idx, common_cols]
        row_csv = csv.loc[idx, common_cols]
        neq = (row_db2.astype(str).values != row_csv.astype(str).values)
        if any(neq):
            diffs.append({
                "key": tuple(idx) if isinstance(idx, tuple) else (idx,),
                "db2": {c: str(row_db2[c]) for c in common_cols},
                "csv": {c: str(row_csv[c]) for c in common_cols},
                "mismatch_cols": [c for i, c in enumerate(common_cols) if neq[i]]
            })
            if len(diffs) >= sample:
                break

    return {
        "db2_only_count": int(len(db2_only_idx)),
        "csv_only_count": int(len(csv_only_idx)),
        "sample_db2_only_keys": [tuple(i) if isinstance(i, tuple) else (i,) for i in db2_only_idx[:sample]],
        "sample_csv_only_keys": [tuple(i) if isinstance(i, tuple) else (i,) for i in csv_only_idx[:sample]],
        "sample_row_mismatches": diffs,
    }
