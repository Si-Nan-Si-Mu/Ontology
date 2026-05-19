"""从 Neo4j 导出 Person 人格分析结果（JSON / 纯文本）。

各 facet 默认聚合**所有导入批次**（按 ``created_at`` 新到旧）；``persona_batch_id`` 字段仍为
``Person.last_persona_batch_id``（最近一次写入指针）。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from app.json_safe import json_safe
from app.db.neo4j import Neo4jConnection


def _collect(
    neo4j: Neo4jConnection,
    *,
    subject_id: str,
    batch_id: str | None,
    rel: str,
    label: str,
    order_key: str | None = None,
    order_desc: bool = False,
) -> list[dict[str, Any]]:
    """``batch_id`` 非空时仅取该批；为空时取该 Person 下该类型的全部 facet（多批次追加）。"""
    if batch_id:
        direction = "DESC" if order_desc else "ASC"
        order_clause = f"n.{order_key} {direction}" if order_key else "elementId(n)"
        q = f"""
        MATCH (anchor:Person) WHERE anchor.username = $sid OR anchor.subject_id = $sid
        MATCH (anchor)-[:{rel}]->(n:{label})
        WHERE n.persona_batch_id = $bid
        RETURN properties(n) AS props
        ORDER BY {order_clause}
        """
        rows = neo4j.execute_read(q, {"sid": subject_id, "bid": batch_id})
    else:
        if order_key:
            sec = "DESC" if order_desc else "ASC"
            order_clause = f"n.created_at DESC, n.{order_key} {sec}"
        else:
            order_clause = "n.created_at DESC, elementId(n) DESC"
        q = f"""
        MATCH (anchor:Person) WHERE anchor.username = $sid OR anchor.subject_id = $sid
        MATCH (anchor)-[:{rel}]->(n:{label})
        RETURN properties(n) AS props
        ORDER BY {order_clause}
        """
        rows = neo4j.execute_read(q, {"sid": subject_id})
    return [json_safe(r["props"]) for r in rows if r.get("props")]


def _one(
    neo4j: Neo4jConnection,
    *,
    subject_id: str,
    batch_id: str | None,
    rel: str,
    label: str,
) -> dict[str, Any] | None:
    items = _collect(neo4j, subject_id=subject_id, batch_id=batch_id, rel=rel, label=label)
    return items[0] if items else None


def build_persona_export_bundle(neo4j: Neo4jConnection, subject_id: str) -> dict[str, Any]:
    rows = neo4j.execute_read(
        """
        MATCH (p:Person) WHERE p.username = $sid OR p.subject_id = $sid
        RETURN properties(p) AS person, p.last_persona_batch_id AS batch_id
        LIMIT 1
        """,
        {"sid": subject_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"未找到 Person: {subject_id}")
    row = rows[0]
    person = json_safe(row.get("person") or {})
    batch_id = row.get("batch_id")
    if batch_id is not None and hasattr(batch_id, "__str__") and not isinstance(batch_id, str):
        batch_id = str(batch_id)

    # 导出聚合全部批次 facet；单条字段取「最新 created_at」对应节点
    facet_batch: str | None = None

    bundle: dict[str, Any] = {
        "export_schema": "pog_persona_export_v1",
        "subject_id": subject_id,
        "persona_batch_id": batch_id,
        "person": person,
        "persona_summary": _one(neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_PERSONA_SUMMARY", label="PersonaSummary"),
        "expression_style": _one(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_EXPRESSION_STYLE", label="ExpressionStyleTrait"
        ),
        "verbal_tics": _collect(neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_VERBAL_TIC", label="VerbalTicObservation"),
        "emotion_dimensions": _collect(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_EMOTION_DIMENSION", label="EmotionDimensionObservation"
        ),
        "social_relation_sketch": _one(
            neo4j,
            subject_id=subject_id,
            batch_id=facet_batch,
            rel="HAS_SOCIAL_RELATION_SKETCH",
            label="SocialRelationSketchFacet",
        ),
        "enneagram_hypothesis": _one(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_ENNEAGRAM_HYPOTHESIS", label="EnneagramHypothesisFacet"
        ),
        "big_five_traits": _collect(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_BIG_FIVE_TRAIT", label="BigFiveTraitFacet"
        ),
        "big_five_sketch_legacy": _one(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_BIG_FIVE_SKETCH", label="BigFiveSketchFacet"
        ),
        "mbti_hypothesis": _one(neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_MBTI_HYPOTHESIS", label="MbtiHypothesisFacet"),
        "analysis_meta": _one(
            neo4j, subject_id=subject_id, batch_id=facet_batch, rel="HAS_PERSONA_ANALYSIS_META", label="PersonaAnalysisMeta"
        ),
        "dialogue_exemplars": _collect(
            neo4j,
            subject_id=subject_id,
            batch_id=facet_batch,
            rel="HAS_DIALOGUE_EXEMPLAR",
            label="DialogueExemplar",
            order_key="order_index",
        ),
        "salient_traits": _collect(
            neo4j,
            subject_id=subject_id,
            batch_id=facet_batch,
            rel="HAS_SALIENT_TRAIT",
            label="SalientTraitObservation",
            order_key="salience_0_1",
            order_desc=True,
        ),
    }

    sk = bundle.get("social_relation_sketch")
    if isinstance(sk, dict) and sk.get("dyadic_relation_type_zh"):
        bundle["dyadic_relationship"] = {
            "type": sk.get("dyadic_relation_type"),
            "type_zh": sk.get("dyadic_relation_type_zh"),
            "confidence": sk.get("dyadic_relation_confidence"),
            "rationale": sk.get("dyadic_relation_rationale"),
        }
    else:
        meta_parsed = None
        meta_node = bundle.get("analysis_meta") or {}
        raw_json = meta_node.get("payload_json") if isinstance(meta_node, dict) else None
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                meta_parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                meta_parsed = None
        if isinstance(meta_parsed, dict) and isinstance(meta_parsed.get("dyadic_relationship"), dict):
            bundle["dyadic_relationship"] = meta_parsed["dyadic_relationship"]

    meta_node = bundle.get("analysis_meta") or {}
    raw_json = meta_node.get("payload_json") if isinstance(meta_node, dict) else None
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            bundle["analysis_meta_parsed"] = json.loads(raw_json)
        except json.JSONDecodeError:
            bundle["analysis_meta_parsed"] = None
    else:
        bundle["analysis_meta_parsed"] = None

    return bundle


def format_persona_export_text(bundle: dict[str, Any]) -> str:
    """人类可读纯文本（非临床声明）。"""
    lines: list[str] = []
    sid = bundle.get("subject_id", "")
    lines.append("=== POG 人格分析导出（探索性假设，非临床/职业测评结论）===")
    lines.append(f"subject_id: {sid}")
    lines.append(f"persona_batch_id: {bundle.get('persona_batch_id')}")
    lines.append("")

    p = bundle.get("person") or {}
    lines.append("[Person]")
    for k in sorted(p.keys()):
        lines.append(f"  {k}: {p[k]}")
    lines.append("")

    ps = bundle.get("persona_summary")
    if isinstance(ps, dict) and ps.get("text"):
        lines.append("[摘要]")
        lines.append(str(ps["text"]))
        lines.append("")

    es = bundle.get("expression_style")
    if isinstance(es, dict) and es.get("description"):
        lines.append("[表达风格]")
        lines.append(str(es["description"]))
        lines.append("")

    for tic in bundle.get("verbal_tics") or []:
        if isinstance(tic, dict):
            lines.append(f"[口癖] {tic.get('pattern_label', '?')} × {tic.get('hit_count', 0)}")

    lines.append("")
    for em in bundle.get("emotion_dimensions") or []:
        if isinstance(em, dict):
            lines.append(
                f"[情绪维度] {em.get('dimension')} score={em.get('score_0_1')} "
                f"method={em.get('method')} — {em.get('caution', '')}"
            )

    lines.append("")
    sk = bundle.get("social_relation_sketch")
    if isinstance(sk, dict):
        lines.append("[社会关系草图]")
        lines.append(f"  channel: {sk.get('channel')}")
        lines.append(f"  interpretation: {sk.get('interpretation')}")
        if sk.get("dyadic_relation_type_zh"):
            lines.append(
                f"  双人关系（探索性）: {sk.get('dyadic_relation_type_zh')} "
                f"(conf={sk.get('dyadic_relation_confidence')})"
            )
            if sk.get("dyadic_relation_rationale"):
                lines.append(f"  依据: {sk.get('dyadic_relation_rationale')}")
        lines.append("")
    dr = bundle.get("dyadic_relationship")
    if isinstance(dr, dict) and dr.get("type_zh") and not isinstance(sk, dict):
        lines.append("[双人关系假设]")
        lines.append(f"  {dr.get('type_zh')} (conf={dr.get('confidence')})")
        if dr.get("rationale"):
            lines.append(f"  {dr.get('rationale')}")
        lines.append("")

    en = bundle.get("enneagram_hypothesis")
    if isinstance(en, dict):
        lines.append("[九型假设]")
        lines.append(
            f"  type={en.get('type_guess')} wing={en.get('wing_guess')} conf={en.get('confidence')} "
            f"src={en.get('source')}"
        )
        lines.append(f"  {en.get('hypothesis_text', '')}")
        lines.append("")

    for bf in bundle.get("big_five_traits") or []:
        if isinstance(bf, dict):
            lines.append(f"[大五] {bf.get('trait')} level={bf.get('level')} — {bf.get('note', '')}")

    leg = bundle.get("big_five_sketch_legacy")
    if isinstance(leg, dict) and leg.get("traits_json"):
        lines.append("")
        lines.append("[大五 JSON 草图（旧版单节点）]")
        lines.append(str(leg.get("traits_json"))[:2000])

    lines.append("")
    mbti = bundle.get("mbti_hypothesis")
    if isinstance(mbti, dict):
        lines.append("[MBTI 假设]")
        lines.append(f"  type_code: {mbti.get('type_code', '')}")
        lines.append(f"  status: {mbti.get('status')} confidence: {mbti.get('confidence')}")
        lines.append(str(mbti.get("hypothesis_text", "")))
        if mbti.get("literature_note"):
            lines.append(f"  文献注记: {mbti.get('literature_note')}")
        lines.append("")

    meta = bundle.get("analysis_meta_parsed")
    if isinstance(meta, dict):
        lines.append("[分析元数据]")
        for k in ("inference_mode", "llm_provider", "llm_model", "llm_status", "heuristic_version"):
            if k in meta:
                lines.append(f"  {k}: {meta[k]}")
        rp = meta.get("llm_review_protocol")
        if isinstance(rp, dict) and rp:
            lines.append("[评审式推理协议（LLM 摘要）]")
            for k in ("stance", "evidence_scope", "limits_paragraph", "ethical_boundary_note"):
                if rp.get(k):
                    lines.append(f"  {k}: {rp[k]}")
            steps = rp.get("inference_steps")
            if isinstance(steps, list):
                for i, s in enumerate(steps[:8], 1):
                    lines.append(f"  步骤{i}: {s}")
            lines.append("")

    for d in bundle.get("dialogue_exemplars") or []:
        if isinstance(d, dict) and d.get("turns_json"):
            lines.append(f"[典型对话 exemplar order={d.get('order_index')}]")
            lines.append(str(d.get("turns_json"))[:1200])
            lines.append("")

    for st in bundle.get("salient_traits") or []:
        if isinstance(st, dict):
            lines.append(
                f"[显著特质] {st.get('category')} · {st.get('label')} "
                f"(salience={st.get('salience_0_1')})"
            )
            if st.get("episode_summary"):
                lines.append(f"  情境摘要: {st['episode_summary']}")
            if st.get("narrative"):
                lines.append(f"  叙述: {st['narrative']}")
            if st.get("supporting_cues"):
                lines.append(f"  线索: {st['supporting_cues']}")
            lines.append("")

    lines.append("=== 导出结束 ===")
    return "\n".join(lines)


def persona_export_json_bytes(bundle: dict[str, Any]) -> bytes:
    return json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
