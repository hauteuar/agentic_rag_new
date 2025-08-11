
import json, os
from typing import List, Dict, Any
from llm_client import LLMClient
from retriever import VectorStore
from storage import DB

SYSTEM_PLAN = """You are an analysis planner. Break the user question into 2-5 bite-size sub-queries.
Return strict JSON:
{"subqueries": ["...","..."], "notes": "short rationale"}
"""

SYSTEM_SYNTH = """You are a careful banking analyst. Use the provided CONTEXT passages to answer.
- Cite using [filename#chunk_id] footnotes.
- If unsure, say what is missing.
- Be concise, accurate, and safe for a private bank environment.
"""

class AgenticRAG:
    def __init__(self, db: DB, vector: VectorStore):
        self.db = db
        self.vector = vector
        self.llm = LLMClient()

    def _plan(self, question: str) -> List[str]:
        msg = [
            {"role": "system", "content": SYSTEM_PLAN},
            {"role": "user", "content": f"Question: {question}"}
        ]
        out = self.llm.chat(msg, temperature=0.2, max_tokens=300)
        try:
            js = json.loads(out)
            subs = js.get("subqueries", [])
            if not subs: subs = [question]
            return subs[:5]
        except Exception:
            return [question]

    def _retrieve(self, subquery: str, k: int = 6, kind_hint: str | None = None) -> List[Dict[str, Any]]:
        hits = self.vector.search(subquery, k=k)
        # return as dicts with score/text/ids
        results = []
        for score, meta in hits:
            results.append({
                "score": score,
                "chunk_id": meta.get("chunk_id"),
                "filename": meta.get("filename"),
                "text": meta.get("text"),
            })

# Heuristic: if question hints at code, DB2, or JCL, rank such chunks slightly higher
if any(kw in subquery.lower() for kw in ["cobol","jcl","copybook","vsam","cics","db2","sql"]):
    for r in results:
        fname = (r.get("filename") or "").lower()
        if any(x in fname for x in ["db2:", ".cbl", ".cob", ".cpy", ".jcl", ".cics"]):
            r["score"] += 0.05
        return results

    def _synthesize(self, question: str, contexts: List[Dict[str, Any]]) -> str:
        context_block = "\n\n".join(
            f"[{c['filename']}#{c['chunk_id']}]\n{c['text']}" for c in contexts
        ) or "(no context)"
        messages = [
            {"role": "system", "content": SYSTEM_SYNTH},
            {"role": "user", "content": f"QUESTION:\n{question}\n\nCONTEXT:\n{context_block}"}
        ]
        return self.llm.chat(messages, temperature=0.0, max_tokens=900)

    def answer(self, session_id: str, question: str) -> Dict[str, Any]:
        # 1) Plan
        subqueries = self._plan(question)

        # 2) Iterative retrieval (agentic loop): retrieve per subquery, then optional refinement
        gathered: List[Dict[str, Any]] = []
        for sq in subqueries:
            hits = self._retrieve(sq, k=6)
            gathered.extend(hits)

        # Optional: refinement step if too few relevant results (score threshold demo)
        if len(gathered) < 3:
            # Ask LLM to suggest a refined query
            refine_msgs = [
                {"role": "system", "content": "Suggest a sharper search query for RAG given the user's question."},
                {"role": "user", "content": question}
            ]
            refined = self.llm.chat(refine_msgs, temperature=0.3, max_tokens=60)
            hits = self._retrieve(refined.strip(), k=6)
            gathered.extend(hits)

        # Deduplicate by chunk_id preserving best score
        seen = {}
        for c in gathered:
            cid = c.get("chunk_id")
            if cid is None: 
                continue
            if cid not in seen or c["score"] > seen[cid]["score"]:
                seen[cid] = c
        contexts = sorted(seen.values(), key=lambda x: -x["score"])[:10]

        # 3) Synthesize
        answer = self._synthesize(question, contexts)

        # citations
        citations = [{"chunk_id": c["chunk_id"], "filename": c["filename"], "score": c["score"]} for c in contexts]
        return {"answer": answer, "citations": citations}
