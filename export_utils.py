
import os, json, datetime
from typing import Dict, Any

def export_markdown(session_id: str, lineage: Dict[str, Any], analysis_answer: str | None, base_dir: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md = [f"# Session {session_id} Analysis ({ts})\n"]
    md.append("## CRUD Map — Files\n")
    for k,v in sorted(lineage.get("files",{}).items()):
        md.append(f"- **{k}**: ops={sorted(list(v.get('ops',{}).keys()))}, programs={', '.join(v.get('programs',[]))}")
    md.append("\n## CRUD Map — Tables\n")
    for k,v in sorted(lineage.get("tables",{}).items()):
        md.append(f"- **{k}**: ops={sorted(list(v.get('ops',{}).keys()))}, programs={', '.join(v.get('programs',[]))}")
    if analysis_answer:
        md.append("\n## LLM Synthesis\n")
        md.append(analysis_answer)
    out_dir = os.path.join(base_dir, "exports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{session_id}_analysis.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    return path
