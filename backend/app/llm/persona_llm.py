"""使用 DeepSeek 对 wx 人格摘要做 LLM 增强（失败时保留启发式结果）。

采用「评审式推理协议」：显式证据范围、对立假设、局限与伦理边界；输出除类型学标签外，
更偏 McAdams 第二层（关切/策略）与可观察沟通—人际特征，并允许**脱敏后的情境摘要**
保留一定「经历感」，禁止复述可识别隐私原文。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import Settings, get_settings
from app.llm.client import chat_json, deepseek_configured

logger = logging.getLogger(__name__)

_MBTI_TYPE_RE = re.compile(r"^[IE][NS][FT][JP]$", re.IGNORECASE)

_SALIENT_CATEGORIES = frozenset(
    {
        "interpersonal_style",
        "coping_self_regulation",
        "values_expressed",
        "discourse_control",
        "conflict_repair",
        "humor_playfulness",
        "agency_communion",
        "attachment_behavioral_hypothesis",
        "social_support_seeking",
        "narrative_concern",
        "motivational_concern",
        "meta_cognition",
        "risk_ethics_tone",
        "other",
    }
)

_SYSTEM_PROMPT = """你是人格心理学方向的**文本证据评审员**。
任务：仅依据给定的即时通讯片段（已标注 self=被分析主体），在**探索性假设**层面做结构化评审。

理论锚点（请在推理中内化，勿在 JSON 外输出长文讨论）：
- McAdams「特质—个人关切—叙事认同」层级：短文本对「特质」与类型学标签证据弱，应更重视**可观察的沟通策略、人际模式、价值表达、叙事关切**（第二层）与**脱敏后的情境主题**（第三层的轻量 proxy），避免把聊天风格等同稳定特质。
- 类型学（MBTI、九型等）在 NLP 文献中效度链弱于维度模型；若输出须标为**弱假设**并给对立解释。
- 人际与表达：可参考人际环状模型（agency/warmth 等）作为**语言—行为线索**的语言组织，不作临床诊断。

必须遵守：
- 仅输出一个合法 JSON 对象，无 Markdown 代码围栏；
- 所有分数为 0~1；不确定则降低置信度、类型填 unknown；
- **禁止**推断 DSM/ICD 诊断、障碍或用药建议；情绪词仅作非临床语义线索；
- **隐私**：不得输出手机号、证件、精确地址、他人真实姓名；对「经历」用**概括性情境句**（episode_summary）描述主题，勿逐字抄录聊天；
- 对每条显著特质须给出**简短行为线索**（supporting_cues），优先转述而非长引原文。"""

_USER_TEMPLATE = """会话：{chat}（{channel}）
被分析主体 sender 标签：{self_label}
有效消息约 {n_used} 条；自己侧发言样本（可能截断）：
---
{self_sample}
---
典型互动轮次（JSON）：
{exemplars_json}

请严格输出 JSON（字段不可缺省；若无内容用空数组 [] 或空字符串 ""）：
{{
  "review_protocol": {{
    "stance": "一句：本分析为探索性文本假设，非测评结论",
    "evidence_scope": "本批证据能支持什么层级（如：表达习惯/回合策略/局部关切），不能外推什么",
    "inference_steps": [
      "步骤1：先列出可观察行为与用词模式",
      "步骤2：区分「状态/情境」与「倾向性假设」",
      "步骤3：给出至少一个对立假设或替代解释",
      "步骤4：检查隐私与过度病理化风险"
    ],
    "rival_hypotheses": ["与主解释并存的简短假设1", "假设2"],
    "limits_paragraph": "80~200字：样本偏差、平台效应、角色扮演、情绪状态等局限",
    "ethical_boundary_note": "一句：不诊断、不评价道德优劣，仅描述沟通—心理线索"
  }},
  "salient_traits": [
    {{
      "trait_key": "snake_case 唯一键，如 humor_self_deprecating",
      "category": "从下列选一：interpersonal_style|coping_self_regulation|values_expressed|discourse_control|conflict_repair|humor_playfulness|agency_communion|attachment_behavioral_hypothesis|social_support_seeking|narrative_concern|motivational_concern|meta_cognition|risk_ethics_tone|other",
      "label": "中文短标签，如「自嘲式幽默」",
      "narrative": "1~3句：该特质在对话中如何体现（非类型学术语优先）",
      "episode_summary": "0~1句：脱敏后的情境主题（如「近期工作压力下的相互安慰」），无可写空串",
      "salience_0_1": 0.0,
      "supporting_cues": "20~80字：转述式线索，勿长引原文"
    }}
  ],
  "motivational_concerns": [
    {{
      "trait_key": "concern_snake_case",
      "category": "motivational_concern",
      "label": "关切主题短名",
      "narrative": "与自我目标、责任、关系任务相关的简述",
      "episode_summary": "脱敏情境或空串",
      "salience_0_1": 0.0,
      "supporting_cues": "线索"
    }}
  ],
  "persona_summary": "240~700字中文：先写显著特质与关切，再补类型学（若有）且强调不确定；可含轻度叙事感但必须脱敏",
  "expression_style": "一句到多句：节奏、礼貌标记、句式复杂度、表情符/语气词习惯等",
  "mbti_hypothesis": "弱假设+对立类型可能+为何聊天证据不足",
  "mbti_type": "四字母或 unknown",
  "mbti_confidence": 0.0,
  "enneagram": {{
    "type_guess": "1-9 或 unknown",
    "wing_guess": "如 5w4 或 unknown",
    "confidence": 0.0,
    "hypothesis_text": "弱假设说明"
  }},
  "emotion_dimensions": [
    {{"dimension": "snake_case", "score_0_1": 0.0, "note": "非临床简短说明"}}
  ],
  "social_relation_interpretation": "在结构线索之上的互动风格（非亲密度打分）",
  "big_five_notes": [
    {{"trait": "Neuroticism|Extraversion|Agreeableness|Conscientiousness|Openness", "level": "low|mid|high|unknown", "note": ""}}
  ]
}}

要求：salient_traits 与 motivational_concerns 合计至少 4 条、至多 12 条；优先写**在文本中反复出现、区分度高**的行为—语言特征，不要堆砌类型学标签。"""


def _clip_self_sample(self_texts: list[str], max_chars: int = 12000) -> str:
    parts: list[str] = []
    n = 0
    for i, t in enumerate(self_texts):
        line = f"[{i + 1}] {t[:800]}"
        if n + len(line) > max_chars:
            break
        parts.append(line)
        n += len(line) + 1
    return "\n".join(parts) if parts else "（自己侧文本极少）"


def _parse_llm_payload(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("根节点须为对象")
    return data


def _slug_trait_key(raw: str, fallback: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (raw or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) > 64:
        s = s[:64].rstrip("_")
    return s or fallback


def _normalize_salient_trait_rows(llm: dict[str, Any]) -> list[dict[str, Any]]:
    """合并 salient_traits 与 motivational_concerns，供 Neo4j 写入。"""
    out: list[dict[str, Any]] = []
    seq = 0
    for block_name in ("salient_traits", "motivational_concerns"):
        block = llm.get(block_name)
        if not isinstance(block, list):
            continue
        for raw in block:
            if not isinstance(raw, dict):
                continue
            cat = str(raw.get("category", "other")).strip().lower() or "other"
            if cat not in _SALIENT_CATEGORIES:
                cat = "other"
            label = str(raw.get("label", "")).strip() or "未命名特质"
            tkey = str(raw.get("trait_key", "")).strip()
            trait_key = _slug_trait_key(tkey, f"trait_{seq}")
            seq += 1
            try:
                sal = float(raw.get("salience_0_1", 0.0) or 0.0)
            except (TypeError, ValueError):
                sal = 0.0
            sal = round(min(1.0, max(0.0, sal)), 3)
            out.append(
                {
                    "trait_key": trait_key[:96],
                    "category": cat[:48],
                    "label": label[:160],
                    "narrative": str(raw.get("narrative", ""))[:900],
                    "episode_summary": str(raw.get("episode_summary", ""))[:420],
                    "supporting_cues": str(raw.get("supporting_cues", ""))[:360],
                    "salience_0_1": sal,
                    "inference_source": "deepseek",
                    "method": "deepseek_persona_review_v1",
                }
            )
            if len(out) >= 12:
                return out
    return out


def _compact_review_protocol(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in ("stance", "evidence_scope", "limits_paragraph", "ethical_boundary_note"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:700]
    rh = raw.get("rival_hypotheses")
    if isinstance(rh, list):
        out["rival_hypotheses"] = [str(x).strip()[:220] for x in rh[:5] if str(x).strip()]
    steps = raw.get("inference_steps")
    if isinstance(steps, list):
        out["inference_steps"] = [str(x).strip()[:280] for x in steps[:8] if str(x).strip()]
    return out


def _merge_meta_json(digest: dict[str, Any], *, extra: dict[str, Any]) -> None:
    meta = json.loads(digest.get("analysis_meta_json") or "{}")
    if not isinstance(meta, dict):
        meta = {}
    meta.update(extra)
    blob = json.dumps(meta, ensure_ascii=False)
    if len(blob) > 7800:
        rp = meta.get("llm_review_protocol")
        if isinstance(rp, dict):
            rp2 = dict(rp)
            rp2["inference_steps"] = (rp2.get("inference_steps") or [])[:3]
            rp2["limits_paragraph"] = str(rp2.get("limits_paragraph", ""))[:400]
            meta["llm_review_protocol"] = rp2
        blob = json.dumps(meta, ensure_ascii=False)
    if len(blob) > 8000:
        meta.pop("llm_review_protocol", None)
        blob = json.dumps(meta, ensure_ascii=False)[:8000]
    else:
        blob = blob[:8000]
    digest["analysis_meta_json"] = blob


def _merge_emotion_dimensions(
    lexical: list[dict[str, Any]],
    llm_rows: Any,
) -> list[dict[str, Any]]:
    if not isinstance(llm_rows, list) or not llm_rows:
        return lexical
    merged: list[dict[str, Any]] = []
    for row in llm_rows[:8]:
        if not isinstance(row, dict):
            continue
        dim = str(row.get("dimension", "")).strip() or "llm_dimension"
        score = row.get("score_0_1", 0.0)
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 0.0
        merged.append(
            {
                "dimension": dim[:128],
                "lexical_hits": 0,
                "score_0_1": round(min(1.0, max(0.0, score_f)), 3),
                "method": "deepseek_persona_review_v1",
                "caution": str(row.get("note", "LLM 推断；非临床"))[:512],
            }
        )
    return merged if merged else lexical


def _merge_big_five(
    lexical: list[dict[str, Any]],
    llm_notes: Any,
) -> list[dict[str, Any]]:
    if not isinstance(llm_notes, list) or not llm_notes:
        return lexical
    note_by_trait = {
        str(x.get("trait", "")): x
        for x in llm_notes
        if isinstance(x, dict) and x.get("trait")
    }
    out: list[dict[str, Any]] = []
    for item in lexical:
        trait = str(item.get("trait", ""))
        base = dict(item)
        extra = note_by_trait.get(trait.replace("_proxy", "")) or note_by_trait.get(trait)
        if extra:
            level = str(extra.get("level", ""))
            note = str(extra.get("note", ""))
            base["level"] = level[:32] if level else "unknown"
            suffix = f" LLM:{level}" if level else ""
            base["note"] = (str(base.get("note", "")) + suffix + (f" {note}" if note else ""))[:512]
            base["method"] = "lexicon+deepseek_review_v1"
        out.append(base)
    return out


def maybe_enrich_persona_digest(
    digest: dict[str, Any],
    *,
    norm: list[dict[str, Any]],
    self_texts: list[str],
    exemplars: list[list[dict[str, Any]]],
    chat: str,
    is_group: bool,
    self_speaker_label: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """若 DeepSeek 已配置则调用 LLM 覆盖摘要/MBTI/九型等；失败则原样返回并记录 meta。"""
    s = settings or get_settings()
    if not deepseek_configured(s):
        return digest

    user_msg = _USER_TEMPLATE.format(
        chat=chat or "?",
        channel="群聊" if is_group else "私聊",
        self_label=self_speaker_label.strip(),
        n_used=digest.get("messages_used", len(norm)),
        self_sample=_clip_self_sample(self_texts),
        exemplars_json=json.dumps(exemplars[:3], ensure_ascii=False)[:6000],
    )
    try:
        raw = chat_json(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=s.deepseek_model,
        )
        llm = _parse_llm_payload(raw)
    except Exception as e:
        logger.warning("DeepSeek persona enrich failed: %s", e)
        meta = json.loads(digest.get("analysis_meta_json") or "{}")
        if not isinstance(meta, dict):
            meta = {}
        meta["llm_provider"] = "deepseek"
        meta["llm_status"] = "error"
        meta["llm_error"] = str(e)[:500]
        digest["analysis_meta_json"] = json.dumps(meta, ensure_ascii=False)[:8000]
        return digest

    if isinstance(llm.get("persona_summary"), str) and llm["persona_summary"].strip():
        digest["persona_summary"] = llm["persona_summary"].strip()[:4000]
    if isinstance(llm.get("expression_style"), str) and llm["expression_style"].strip():
        digest["expression_style"] = llm["expression_style"].strip()[:1024]
    if isinstance(llm.get("mbti_hypothesis"), str) and llm["mbti_hypothesis"].strip():
        digest["mbti_hypothesis"] = llm["mbti_hypothesis"].strip()[:900]
        digest["mbti_status"] = "llm_hypothesis"
        try:
            digest["mbti_confidence"] = float(llm.get("mbti_confidence", 0.3))
        except (TypeError, ValueError):
            digest["mbti_confidence"] = 0.3
    mbti_type = str(llm.get("mbti_type", "")).strip().upper()
    if mbti_type and mbti_type != "UNKNOWN" and _MBTI_TYPE_RE.match(mbti_type):
        digest["mbti_type_code"] = mbti_type

    ennea = llm.get("enneagram")
    if isinstance(ennea, dict):
        digest["enneagram_hypothesis"] = {
            "type_guess": str(ennea.get("type_guess", "unknown"))[:32],
            "wing_guess": str(ennea.get("wing_guess", "unknown"))[:32],
            "confidence": float(ennea.get("confidence", 0.0) or 0.0),
            "hypothesis_text": str(ennea.get("hypothesis_text", ""))[:900],
            "source": "deepseek",
            "status": "llm_hypothesis",
        }

    digest["emotion_dimensions"] = _merge_emotion_dimensions(
        digest.get("emotion_dimensions") or [],
        llm.get("emotion_dimensions"),
    )
    digest["big_five_lexical_sketch"] = _merge_big_five(
        digest.get("big_five_lexical_sketch") or [],
        llm.get("big_five_notes"),
    )

    sk = digest.get("social_relation_sketch")
    interp = llm.get("social_relation_interpretation")
    if isinstance(sk, dict) and isinstance(interp, str) and interp.strip():
        sk = dict(sk)
        sk["interpretation"] = interp.strip()[:512]
        sk["interpretation_source"] = "deepseek"
        digest["social_relation_sketch"] = sk

    digest["salient_trait_observations"] = _normalize_salient_trait_rows(llm)

    rp = _compact_review_protocol(llm.get("review_protocol"))
    _merge_meta_json(
        digest,
        extra={
            "heuristic_version": "wx_persona_v2",
            "inference_mode": "heuristic+deepseek",
            "llm_provider": "deepseek",
            "llm_model": s.deepseek_model,
            "llm_status": "ok",
            "llm_prompt_version": "pog_deepseek_review_v1",
            "references_doc": "docs/PERSONA_INFERENCE_REFERENCES.md",
            "llm_review_protocol": rp,
            "salient_trait_count": len(digest.get("salient_trait_observations") or []),
        },
    )
    return digest
