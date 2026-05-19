"""从 wx-cli 消息列表生成「人格/表达」摘要与典型互动片段（不落库逐条对话）。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ingest.wx_speakers import EMPTY_SENDER_UI_LABEL, canonical_sender_label, display_sender_label
_TIC_PATTERNS = [
    ("哈哈", r"哈哈{1,}|hhh+|xswl"),
    ("嗯/呃", r"[嗯呃哦噢欸诶]+"),
    ("就是", r"就是说|就是啊|反正"),
    ("真的", r"真的假的|真的吗|我天"),
    ("可能", r"可能吧|也许|大概"),
    ("不过", r"不过|但是|然而"),
]


def _text(m: dict[str, Any]) -> str:
    c = m.get("content")
    if c is None:
        return ""
    return c if isinstance(c, str) else str(c)


def _sender(m: dict[str, Any]) -> str:
    return (m.get("sender") or "").strip() if isinstance(m, dict) else ""


def _time(m: dict[str, Any]) -> str:
    t = m.get("time")
    if isinstance(t, str):
        return t
    return str(t) if t is not None else ""


def _normalize_messages(
    messages: list[Any],
    profiled_speaker_label: str,
    *,
    wx_me_sender_label: str = "",
) -> list[dict[str, Any]]:
    """转为带 role 的条目。

    - ``self``：被分析对象（人格画像主体）的发言
    - ``peer``：本机微信或其它对端发言
  空 ``sender`` 在 wx-cli 私聊中**可能是本机也可能是对方**，须由 ``wx_me_sender_label`` 与
    ``profiled_speaker_label`` 共同判定，不能一律记为 anonymous。
    """
    out: list[dict[str, Any]] = []
    profiled = canonical_sender_label(profiled_speaker_label)
    me = canonical_sender_label(wx_me_sender_label)

    for m in messages:
        if not isinstance(m, dict):
            continue
        text = _text(m).strip()
        if not text:
            continue
        if text.startswith("[图片]") and len(text) < 40:
            continue
        sender_raw = _sender(m)
        sender = canonical_sender_label(sender_raw)

        if sender == profiled:
            role = "self"
        elif sender == me:
            role = "peer"
        elif sender:
            role = "peer"
        elif profiled == "":
            role = "self"
        else:
            role = "peer"

        out.append(
            {
                "sender": sender_raw,
                "sender_canonical": sender,
                "role": role,
                "text": text[:2000],
                "time": _time(m),
            }
        )
    return out


def _count_tics(texts: list[str]) -> list[dict[str, Any]]:
    blob = "\n".join(texts)
    found: list[dict[str, Any]] = []
    for name, pat in _TIC_PATTERNS:
        n = len(re.findall(pat, blob, flags=re.IGNORECASE))
        if n > 0:
            found.append({"name": name, "count": n})
    found.sort(key=lambda x: -x["count"])
    return found[:8]


def _lex_hits(blob: str, pattern: str) -> int:
    if not blob.strip():
        return 0
    return len(re.findall(pattern, blob))


def build_emotion_dimension_observations(self_texts: list[str]) -> list[dict[str, Any]]:
    """基于中文情绪相关词簇的**非临床**计数；每条记录将来对应一个 `EmotionDimensionObservation` 节点。"""
    blob = "\n".join(self_texts) if self_texts else ""
    if not blob.strip():
        return [
            {
                "dimension": "sparse_self_text",
                "lexical_hits": 0,
                "score_0_1": 0.0,
                "method": "zh_lexicon_v1_nonclinical",
                "caution": "自己侧文本过少，情绪维度不作推断",
            }
        ]

    spec: list[tuple[str, str]] = [
        ("positive_affect", r"开心|高兴|谢谢|喜欢|棒|太好了|不错|好耶|爱你"),
        ("negative_affect", r"烦|累|难|焦虑|担心|害怕|郁闷|崩溃|无语"),
        ("anger_frustration", r"生气|讨厌|气死|烦死|妈的|卧槽|滚"),
        ("social_warmth", r"麻烦你了|不好意思|辛苦|请教|拜托"),
        ("certainty_markers", r"肯定|一定|绝对|必须|算了|就这样吧"),
    ]
    total_chars = max(len(blob), 1)
    rows: list[dict[str, Any]] = []
    for dim, pat in spec:
        h = _lex_hits(blob, pat)
        if h == 0:
            continue
        score = round(min(1.0, h / (total_chars / 100.0 + 2.0)), 3)
        rows.append(
            {
                "dimension": dim,
                "lexical_hits": h,
                "score_0_1": score,
                "method": "zh_lexicon_v1_nonclinical",
                "caution": "非临床量表；仅供探索，与 DSM/ICD 无关",
            }
        )
    rows.sort(key=lambda r: -r["score_0_1"])
    if not rows:
        rows.append(
            {
                "dimension": "neutral_or_unmarked",
                "lexical_hits": 0,
                "score_0_1": 0.0,
                "method": "zh_lexicon_v1_nonclinical",
                "caution": "未检出显著情绪词簇；不代表无情绪体验",
            }
        )
    return rows[:8]


def build_social_relation_sketch(
    norm: list[dict[str, Any]],
    *,
    is_group: bool,
    chat: str,
) -> dict[str, Any]:
    """社会关系**结构线索**（对端人数、匿名比例等），非关系质量评判。"""
    peers = {x["sender"] for x in norm if x["role"] == "peer" and x.get("sender")}
    n_self = sum(1 for x in norm if x["role"] == "self")
    n_peer = sum(1 for x in norm if x["role"] == "peer")
    n_peer_empty = sum(
        1 for x in norm if x["role"] == "peer" and not canonical_sender_label(x.get("sender"))
    )
    n = max(len(norm), 1)
    return {
        "channel": "group" if is_group else "private",
        "session_label": (chat or "")[:200],
        "distinct_peer_senders": len(peers),
        "turns_self": n_self,
        "turns_peer": n_peer,
        "turns_peer_empty_sender": n_peer_empty,
        "turns_anonymous_sender": n_peer_empty,
        "self_turn_ratio": round(n_self / n, 3),
        "interpretation": (
            "私聊对偶互动为主"
            if not is_group and len(peers) <= 1
            else "群聊或多方昵称并存（仅结构线索，不推断亲密度）"
        ),
        "interpretation_source": "heuristic",
    }


def build_enneagram_hypothesis() -> dict[str, Any]:
    """九型：**占位**。定号需量表/访谈；短对话机械分类效度不足。"""
    return {
        "type_guess": "unknown",
        "wing_guess": "unknown",
        "confidence": 0.0,
        "hypothesis_text": (
            "九型人格不宜从短对话机械定号；需 RHETI 等量表或深度访谈后再写入高置信度假设。"
        ),
        "source": "placeholder",
    }


def build_big_five_lexical_sketch(self_texts: list[str]) -> list[dict[str, Any]]:
    """大五维度的**极粗**词典代理（启发式），对齐文献中「语言-人格」路径而非 MBTI 类型学。"""
    b = "\n".join(self_texts)

    def c(pat: str) -> int:
        return _lex_hits(b, pat)

    return [
        {
            "trait": "Neuroticism_proxy",
            "lexical_hits": c(r"焦虑|担心|烦|累|崩溃|害怕"),
            "note": "负向情绪词频粗代理，非 NEO-PI-R",
        },
        {
            "trait": "Extraversion_proxy",
            "lexical_hits": c(r"！|哈哈|嗨|兄弟们|大家"),
            "note": "能量/社交外显线索极粗代理",
        },
        {
            "trait": "Agreeableness_proxy",
            "lexical_hits": c(r"谢谢|不好意思|麻烦|辛苦|拜托|理解"),
            "note": "礼貌与合作性线索",
        },
        {
            "trait": "Conscientiousness_proxy",
            "lexical_hits": c(r"计划|安排|进度|截止|明天|下周|一定完成"),
            "note": "结构化与承诺线索",
        },
        {
            "trait": "Openness_proxy",
            "lexical_hits": c(r"为什么|如果|想法|好奇|试试|新"),
            "note": "认知探索线索",
        },
    ]


def _pick_exemplar_threads(norm: list[dict[str, Any]], *, max_threads: int = 4, window: int = 2) -> list[list[dict[str, Any]]]:
    """选若干组连续轮次，偏好 self/peer 交替且文本信息量适中。"""
    threads: list[list[dict[str, Any]]] = []
    i = 0
    while i < len(norm) - 1 and len(threads) < max_threads:
        chunk = norm[i : i + window]
        if len(chunk) < 2:
            break
        a, b = chunk[0], chunk[1]
        if len(a["text"]) < 8 or len(b["text"]) < 8:
            i += 1
            continue
        if len(a["text"]) > 600 or len(b["text"]) > 600:
            i += 1
            continue
        roles = {a["role"], b["role"]}
        if roles <= {"peer"} and "self" not in roles:
            i += 1
            continue
        if "self" in roles and "peer" in roles:
            threads.append(
                [
                    {"role": a["role"], "text": a["text"], "time": a["time"]},
                    {"role": b["role"], "text": b["text"], "time": b["time"]},
                ]
            )
            i += window
        else:
            i += 1
    if not threads:
        for i in range(len(norm) - 1):
            a, b = norm[i], norm[i + 1]
            if len(a["text"]) >= 12 and len(b["text"]) >= 12:
                threads.append(
                    [
                        {"role": a["role"], "text": a["text"], "time": a["time"]},
                        {"role": b["role"], "text": b["text"], "time": b["time"]},
                    ]
                )
                if len(threads) >= max_threads:
                    break
    return threads


def build_persona_digest(
    messages: list[Any],
    *,
    profiled_speaker_label: str,
    wx_me_sender_label: str = "",
    chat: str,
    is_group: bool,
    use_llm: bool = True,
    self_speaker_label: str | None = None,
) -> dict[str, Any]:
    """生成写入 Person 的摘要结构；DeepSeek 已配置且 use_llm 时在启发式基础上 LLM 增强。

    ``profiled_speaker_label``：被分析对象在 JSON 中的 sender（空 sender 传 '' 或 '(空 sender)'）。
    ``wx_me_sender_label``：本机微信在 JSON 中的 sender，wx-cli 私聊多为空。
    ``self_speaker_label``：已废弃别名，等同 profiled_speaker_label。
    """
    if self_speaker_label is not None and not canonical_sender_label(profiled_speaker_label):
        profiled_speaker_label = self_speaker_label
    norm = _normalize_messages(
        messages,
        profiled_speaker_label,
        wx_me_sender_label=wx_me_sender_label,
    )
    if not norm:
        raise ValueError("没有可用于分析的有效消息")

    self_texts = [x["text"] for x in norm if x["role"] == "self"]
    peer_texts = [x["text"] for x in norm if x["role"] == "peer"]
    anon_n = sum(1 for x in norm if x["role"] == "peer" and not canonical_sender_label(x.get("sender")))

    self_avg = sum(len(t) for t in self_texts) / max(len(self_texts), 1)
    peer_avg = sum(len(t) for t in peer_texts) / max(len(peer_texts), 1) if peer_texts else 0.0

    tics = _count_tics(self_texts if self_texts else [x["text"] for x in norm])
    tic_line = "、".join(f"{t['name']}×{t['count']}" for t in tics[:5]) if tics else "（未检出显著高频口癖）"

    style_bits = []
    if self_avg > peer_avg * 1.2 and peer_avg > 0:
        style_bits.append("自述句偏长，展开较多")
    elif peer_avg > self_avg * 1.2 and self_avg > 0:
        style_bits.append("对端发言平均更长")
    if self_avg < 25:
        style_bits.append("自己发言偏短、回合感强")
    if is_group:
        style_bits.append("群聊语境")
    expression_style = "；".join(style_bits) if style_bits else "中性表达节奏（启发式）"

    persona_summary = (
        f"基于 {len(norm)} 条有效消息（会话「{chat or '?'}」）的启发式摘要："
        f"自己侧约 {len(self_texts)} 条，对端约 {len(peer_texts)} 条，空 sender 对端约 {anon_n} 条。"
        f" 口癖线索：{tic_line}。"
        " MBTI 等需接入 LLM 后推断，当前为占位。"
    )

    exemplars = _pick_exemplar_threads(norm)
    emotion_dims = build_emotion_dimension_observations(self_texts)
    social_sketch = build_social_relation_sketch(norm, is_group=is_group, chat=chat)
    ennea = build_enneagram_hypothesis()
    big5 = build_big_five_lexical_sketch(self_texts)
    mbti_text = (
        "未接入 LLM；请在抽取管线中替换为推断结果。"
        " 文献上文本单模态 MBTI 预测难度大，建议与大五等维度对齐（见 docs/PERSONA_INFERENCE_REFERENCES.md）。"
    )[:900]
    mbti_lit = (
        "参考：Holtgraves (2011) 短信与人格及社会语境；"
        "EACL 等讨论 MBTI 从文本预测之局限；PLOS ONE 综述 NLP 与人格测量。"
    )[:900]

    digest: dict[str, Any] = {
        "persona_summary": persona_summary[:4000],
        "expression_style": expression_style[:1024],
        "verbal_tics_list": tics,
        "verbal_tics_json": json.dumps(tics, ensure_ascii=False)[:4000],
        "mbti_hypothesis": mbti_text,
        "mbti_literature_note": mbti_lit,
        "mbti_status": "placeholder",
        "emotion_dimensions": emotion_dims,
        "social_relation_sketch": social_sketch,
        "enneagram_hypothesis": ennea,
        "big_five_lexical_sketch": big5,
        "exemplar_threads": exemplars,
        "interaction_samples_json": json.dumps(exemplars, ensure_ascii=False)[:16000],
        "analysis_meta_json": json.dumps(
            {
                "chat": chat,
                "is_group": is_group,
                "messages_total": len(messages),
                "messages_used": len(norm),
                "self_speaker_label": canonical_sender_label(profiled_speaker_label) or EMPTY_SENDER_UI_LABEL,
                "profiled_speaker_label": display_sender_label(profiled_speaker_label),
                "wx_me_sender_label": display_sender_label(wx_me_sender_label),
                "heuristic_version": "wx_persona_v2",
                "inference_mode": "heuristic",
                "references_doc": "docs/PERSONA_INFERENCE_REFERENCES.md",
            },
            ensure_ascii=False,
        )[:8000],
        "messages_used": len(norm),
        "exemplar_thread_count": len(exemplars),
    }

    if use_llm:
        from app.llm.persona_llm import maybe_enrich_persona_digest

        digest = maybe_enrich_persona_digest(
            digest,
            norm=norm,
            self_texts=self_texts,
            exemplars=exemplars,
            chat=chat,
            is_group=is_group,
            self_speaker_label=display_sender_label(profiled_speaker_label),
            counterparty_speaker_label=(
                "" if is_group else display_sender_label(wx_me_sender_label)
            ),
        )

    return digest
