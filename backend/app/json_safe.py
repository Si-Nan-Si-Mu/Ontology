"""Neo4j Driver 返回值转 JSON 可序列化结构。"""

from __future__ import annotations

import json
from typing import Any


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    mod = type(value).__module__
    name = type(value).__name__
    if mod.startswith("neo4j") and name in ("DateTime", "Date", "Time", "Duration"):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return json.loads(json.dumps(value, default=str))
