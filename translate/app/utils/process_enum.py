from __future__ import annotations

from typing import List, Dict

import psutil


def list_processes(limit: int = 200) -> List[Dict[str, str]]:
    items = []
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        info = proc.info
        name = info.get("name") or ""
        if not name:
            continue
        items.append({"pid": info.get("pid"), "name": name})
        if len(items) >= limit:
            break
    # Deduplicate by name, prefer latest
    seen = set()
    out = []
    for it in reversed(items):
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        out.append(it)
    return list(reversed(out))







