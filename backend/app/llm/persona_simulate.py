"""第一人称风格模拟：仅以 Neo4j 人格子图为事实与风格依据。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings, get_settings
from app.graph_context import format_context_for_prompt
from app.llm.client import chat_json, chat_text, deepseek_configured

logger = logging.getLogger(__name__)

_SYSTEM_JSON = """你是 POG 人格本体图上的**第一人称表达模拟器**（非真人、非诊断）。

规则：
1. 仅将下方「图谱上下文」中的内容当作关于该角色的**已收录事实与风格线索**；不得编造具体经历、关系人姓名、地点、职业、健康诊断等图中未出现的信息。
2. 用**第一人称**（「我」）回复，语气与用词应贴合 expression_style、verbal_tics、dialogue_exemplars 与 salient_traits；可短可长，像即时通讯。
3. 若用户问题涉及图中没有的信息：用角色口吻**坦诚不确定**或**委婉回避**，并在 out_of_graph_note 中说明「图谱未收录」。
4. 这是**探索性模拟**，不是该真人；禁止声称自己是真人或代替其做法律/医疗/财务承诺。
5. 输出**唯一** JSON 对象（无 Markdown 围栏），字段：
   reply（string，模拟发言正文）,
   style_cues_used（string[]，用到的风格/口癖要点，≤6）,
   graph_facts_used（string[]，引用的图谱要点短语，≤6）,
   out_of_graph_note（string，若无图外推测则空字符串）,
   confidence_0_1（number 0~1，对本次贴合图谱的确信度）"""

_SYSTEM_TEXT = """你是 POG 人格本体图上的**第一人称表达模拟器**（非真人、非诊断）。
仅依据用户提供的图谱上下文作答；用第一人称；不得编造图中未收录的具体事实。
若信息不足，在回复中坦诚不确定。回复为纯文本，不要 JSON。"""

_USER_TEMPLATE = """【图谱上下文 JSON】
{context_json}

【可选情境】{scenario}

【对话历史】（最近几轮，可能为空）
{history_block}

【用户此刻对你说】
{user_message}

请生成你的第一人称回复。"""


def _format_history(history: list[dict[str, Any]] | None) -> str:
    if not history:
        return "（无）"
    lines: list[str] = []
    for h in history[-8:]:
        if not isinstance(h, dict):
            continue
        role = str(h.get("role") or "user").strip().lower()
        content = str(h.get("content") or "").strip()[:800]
        if not content:
            continue
        label = "用户" if role == "user" else "模拟角色"
        lines.append(f"{label}: {content}")
    return "\n".join(lines) if lines else "（无）"


def simulate_first_person(
    *,
    context_pack: dict[str, Any],
    user_message: str,
    scenario: str | None = None,
    history: list[dict[str, Any]] | None = None,
    prefer_json: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """返回模拟结果 dict；DeepSeek 未配置时抛出 RuntimeError。"""
    s = settings or get_settings()
    if not deepseek_configured(s):
        raise RuntimeError("DeepSeek 未配置：请在 backend/.env 设置 DEEPSEEK_ENABLED=true 与 DEEPSEEK_API_KEY")

    user_message = (user_message or "").strip()
    if not user_message:
        raise ValueError("user_message 不能为空")

    context_json = format_context_for_prompt(context_pack)
    display = context_pack.get("display_name") or context_pack.get("subject_id") or "角色"
    user_block = _USER_TEMPLATE.format(
        context_json=context_json[:28000],
        scenario=(scenario or "").strip() or "（未指定，按日常私聊语气）",
        history_block=_format_history(history),
        user_message=user_message[:4000],
    )

    meta_base = {
        "subject_id": context_pack.get("subject_id"),
        "persona_batch_id": context_pack.get("persona_batch_id"),
        "trim": context_pack.get("_trim"),
        "mode": "first_person_simulate",
    }

    if prefer_json:
        try:
            raw = chat_json(
                messages=[
                    {"role": "system", "content": _SYSTEM_JSON},
                    {"role": "user", "content": user_block},
                ],
                model=s.deepseek_model,
            )
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("非对象 JSON")
            reply = str(data.get("reply") or "").strip()
            if not reply:
                raise ValueError("空 reply")
            return {
                "reply": reply,
                "style_cues_used": data.get("style_cues_used") if isinstance(data.get("style_cues_used"), list) else [],
                "graph_facts_used": data.get("graph_facts_used") if isinstance(data.get("graph_facts_used"), list) else [],
                "out_of_graph_note": str(data.get("out_of_graph_note") or "").strip(),
                "confidence_0_1": data.get("confidence_0_1"),
                "display_name": display,
                "disclaimer_zh": (
                    "探索性第一人称模拟，基于 Neo4j 人格子图与风格节点，"
                    "不代表真人真实想法或行为，非临床/人事决策依据。"
                ),
                "meta": {**meta_base, "llm_format": "json"},
            }
        except Exception as e:
            logger.warning("simulate JSON mode failed, fallback to text: %s", e)

    text = chat_text(
        messages=[
            {"role": "system", "content": _SYSTEM_TEXT},
            {"role": "user", "content": user_block},
        ],
        model=s.deepseek_model,
    )
    return {
        "reply": text,
        "style_cues_used": [],
        "graph_facts_used": [],
        "out_of_graph_note": "",
        "confidence_0_1": None,
        "display_name": display,
        "disclaimer_zh": (
            "探索性第一人称模拟，基于 Neo4j 人格子图；不代表真人，非诊断依据。"
        ),
        "meta": {**meta_base, "llm_format": "text_fallback"},
    }
