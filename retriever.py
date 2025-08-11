
import os, json
from typing import List, Dict, Any, Tuple
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import os
os.environ.setdefault('HF_HUB_OFFLINE', os.getenv('HF_HUB_OFFLINE','1'))
os.environ.setdefault('TRANSFORMERS_OFFLINE', os.getenv('TRANSFORMERS_OFFLINE','1'))

def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10
    return vectors / norms

class VectorStore:
    def __init__(self, index_path: str):
        self.index_path = index_path
        self.model_name = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.model = SentenceTransformer(self.model_name)
        self.index = None
        self.metadata: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if os.path.exists(self.index_path) and os.path.exists(self.index_path + ".meta.json"):
            self.index = faiss.read_index(self.index_path)
            with open(self.index_path + ".meta.json", "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
        else:
            self.index = None
            self.metadata = []

    def _save(self):
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        if self.index is not None:
            faiss.write_index(self.index, self.index_path)
        with open(self.index_path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False)

    def add_texts(self, texts: List[str], metadatas: List[Dict[str, Any]]):
        embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        d = embeddings.shape[1]
        if self.index is None:
            self.index = faiss.IndexFlatIP(d)
        self.index.add(embeddings.astype(np.float32))
        self.metadata.extend(metadatas)
        self._save()

    def search(self, query: str, k: int = 6) -> List[Tuple[float, Dict[str, Any]]]:
        q_emb = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
        if self.index is None or self.index.ntotal == 0:
            return []
        scores, idxs = self.index.search(q_emb, k)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1: 
                continue
            meta = self.metadata[idx]
            results.append((float(score), meta))
        return results
