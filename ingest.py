
import io, os, json, re
from typing import List, Dict, Any
from pypdf import PdfReader
from docx import Document as Docx
import chardet
from storage import DB
from retriever import VectorStore

class TextIngestor:
    def __init__(self, db: DB, vector: VectorStore, chunk_size: int = 1200, chunk_overlap: int = 180):
        self.db = db
        self.vector = vector
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def extract_text(self, filename: str, content: bytes) -> str:
        name = filename.lower()
        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if name.endswith(".docx"):
            doc = Docx(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        # try text
        detected = chardet.detect(content) or {"encoding": "utf-8"}
        try:
            return content.decode(detected.get("encoding", "utf-8"), errors="ignore")
        except Exception:
            return content.decode("utf-8", errors="ignore")

    def _chunk(self, text: str) -> List[str]:
        text = re.sub(r"\s+"," ", text).strip()
        chunks = []
        start = 0
        n = len(text)
        while start < n:
            end = min(n, start + self.chunk_size)
            chunk = text[start:end]
            chunks.append(chunk)
            if end == n: break
            start = end - self.chunk_overlap
            if start < 0: start = 0
        return chunks

    def ingest_text(self, session_id: str, filename: str, text: str) -> int:
        chunks = self._chunk(text)
        metas = []
        for i, c in enumerate(chunks):
            cid = self.db.add_chunk(session_id, filename, i, c)
            metas.append({"chunk_id": cid, "session_id": session_id, "filename": filename, "text": c})
        self.vector.add_texts([m["text"] for m in metas], metas)
        return len(chunks)
