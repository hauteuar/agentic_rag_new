
import os, time, sqlite3
from typing import List, Dict, Any, Optional

def ensure_dirs(path: str):
    os.makedirs(path, exist_ok=True)

class DB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                citations TEXT,
                created_at REAL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                filename TEXT,
                position INTEGER,
                content TEXT
            );
            """)
            con.commit()

    def create_session(self, name: str) -> str:
        sid = f"S{int(time.time()*1000)}"
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO sessions(id, name, created_at) VALUES (?, ?, ?)", (sid, name, time.time()))
            con.commit()
        return sid

    def list_sessions(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            rows = cur.execute("SELECT id, name, created_at FROM sessions ORDER BY created_at DESC").fetchall()
        return [{"id": r[0], "name": r[1], "created_at": r[2]}] if rows else []

    def session_exists(self, sid: str) -> bool:
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            row = cur.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone()
            return row is not None

    def add_message(self, session_id: str, role: str, content: str, citations: Optional[str] = None):
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO messages(session_id, role, content, citations, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, citations, time.time())
            )
            con.commit()

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            rows = cur.execute(
                "SELECT role, content, citations, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            ).fetchall()
        return [{"role": r[0], "content": r[1], "citations": r[2], "created_at": r[3]} for r in rows]

    def add_chunk(self, session_id: str, filename: str, position: int, content: str) -> int:
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO chunks(session_id, filename, position, content) VALUES (?, ?, ?, ?)",
                (session_id, filename, position, content)
            )
            con.commit()
            return cur.lastrowid

    def get_chunk(self, chunk_id: int) -> str:
        with sqlite3.connect(self.db_path) as con:
            cur = con.cursor()
            row = cur.execute("SELECT content FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
            return row[0] if row else ""
