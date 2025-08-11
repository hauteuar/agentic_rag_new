# code_ingest.py
import re
from typing import List, Dict, Any
from storage import DB
from retriever import VectorStore

MAINFRAME_EXTS = (".cbl", ".cob", ".cpy", ".jcl", ".cics", ".pli", ".sql", ".asm", ".map")

class CodeIngestor:
    """Chunk code with line numbers preserved for better pinpointing."""
    def __init__(self, db: DB, vector: VectorStore, lines_per_chunk: int = 120):
        self.db = db
        self.vector = vector
        self.lines_per_chunk = lines_per_chunk

    def ingest_code(self, session_id: str, filename: str, code_text: str) -> int:
        lines = code_text.splitlines()
        chunks: List[str] = []
        for i in range(0, len(lines), self.lines_per_chunk):
            block = lines[i:i + self.lines_per_chunk]
            numbered = "\n".join(f"{i+1+j:05d}: {ln}" for j, ln in enumerate(block))
            chunks.append(numbered)

        metas: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            cid = self.db.add_chunk(session_id, filename, idx, chunk)
            metas.append({
                "chunk_id": cid,
                "session_id": session_id,
                "filename": filename,
                "text": chunk,
                "kind": "code",
            })
        self.vector.add_texts([m["text"] for m in metas], metas)
        return len(chunks)
