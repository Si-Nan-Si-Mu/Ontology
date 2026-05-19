"""从 persona-export 组装供 LLM 使用的有界图上下文（第一层 / 模拟）。"""

from __future__ import annotations

import json
from typing import Any


def _clip(s: Any, max_len: int) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _trim_exemplar(ex: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"title": _clip(ex.get("title") or ex.get("thread_title"), 80)}
    turns = ex.get("turns") or ex.get("messages") or ex.get("turns_json") or []
    if isinstance(turns, str):
        try:
            turns = json.loads(turns)
        except json.JSONDecodeError:
            turns = []
    trimmed: list[dict[str, str]] = []
    if isinstance(turns, list):
        for t in turns[:6]:
            if not isinstance(t, dict):
                continue
            trimmed.append(
                {
                    "role": _clip(t.get("role") or t.get("sender"), 32),
                    "text": _clip(t.get("text") or t.get("content"), 220),
                }
            )
    out["turns"] = trimmed
    return out


def build_graph_context_pack(bundle: dict[str, Any]) -> dict[str, Any]:
    """确定性裁剪：仅保留模拟/叙述所需 facet 字段。"""
    person = bundle.get("person") if isinstance(bundle.get("person"), dict) else {}
    display = _clip(person.get("display_name") or person.get("subject_id"), 64)
    summary_node = bundle.get("persona_summary") or {}
    summary_text = ""
    if isinstance(summary_node, dict):
        summary_text = _clip(
            summary_node.get("text") or summary_node.get("summary_text"), 1200
        )

    style_node = bundle.get("expression_style") or {}
    style_text = ""
    if isinstance(style_node, dict):
        style_text = _clip(
            style_node.get("description") or style_node.get("style_description") or style_node.get("text"),
            600,
        )

    tics: list[dict[str, str]] = []
    for t in (bundle.get("verbal_tics") or [])[:10]:
        if not isinstance(t, dict):
            continue
        tics.append(
            {
                "name": _clip(t.get("tic_name") or t.get("name"), 48),
                "example": _clip(t.get("example_phrase") or t.get("example"), 80),
            }
        )

    salient: list[dict[str, str]] = []
    for st in (bundle.get("salient_traits") or [])[:8]:
        if not isinstance(st, dict):
            continue
        salient.append(
            {
                "trait_key": _clip(st.get("trait_key"), 64),
                "label_zh": _clip(st.get("label_zh") or st.get("trait_label_zh"), 64),
                "cues": _clip(st.get("supporting_cues") or st.get("rationale"), 200),
            }
        )

    exemplars = [
        _trim_exemplar(ex)
        for ex in (bundle.get("dialogue_exemplars") or [])[:4]
        if isinstance(ex, dict)
    ]

    mbti = bundle.get("mbti_hypothesis") or {}
    mbti_line = ""
    if isinstance(mbti, dict):
        mbti_line = _clip(
            mbti.get("type_code") or mbti.get("hypothesis_text") or mbti.get("summary"),
            200,
        )

    social = bundle.get("social_relation_sketch") or {}
    social_line = ""
    if isinstance(social, dict):
        social_line = _clip(social.get("sketch_text") or social.get("summary"), 400)

    pack = {
        "subject_id": bundle.get("subject_id"),
        "persona_batch_id": bundle.get("persona_batch_id"),
        "display_name": display,
        "persona_summary": summary_text,
        "expression_style": style_text,
        "verbal_tics": tics,
        "salient_traits": salient,
        "dialogue_exemplars": exemplars,
        "mbti_hypothesis": mbti_line,
        "social_relation_sketch": social_line,
        "dyadic_relationship": bundle.get("dyadic_relationship"),
    }
    raw_len = len(json.dumps(bundle, ensure_ascii=False))
    pack_len = len(json.dumps(pack, ensure_ascii=False))
    pack["_trim"] = {
        "source_bytes": raw_len,
        "pack_bytes": pack_len,
        "exemplar_count": len(exemplars),
        "salient_trait_count": len(salient),
    }
    return pack


def format_context_for_prompt(pack: dict[str, Any]) -> str:
    """嵌入 prompt 的 JSON 文本（不含 _trim）。"""
    body = {k: v for k, v in pack.items() if not str(k).startswith("_")}
    return json.dumps(body, ensure_ascii=False, indent=2)
