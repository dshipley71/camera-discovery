from __future__ import annotations
import json, re
from typing import Any

def extract_json_object(text: str) -> dict[str, Any]:
    if not text: return {}
    text = text.strip()
    try:
        obj=json.loads(text); return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError: pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S|re.I)
    if m:
        try:
            obj=json.loads(m.group(1)); return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError: pass
    start,end=text.find("{"),text.rfind("}")
    if start>=0 and end>start:
        try:
            obj=json.loads(text[start:end+1]); return obj if isinstance(obj,dict) else {}
        except json.JSONDecodeError: return {}
    return {}
