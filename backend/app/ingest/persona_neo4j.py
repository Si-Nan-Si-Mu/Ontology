"""Person 特质子图 Neo4j 写入规范（对齐 DeepSeek / 启发式 digest）。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

# 批次内所有可删除的特质节点标签（含历史标签）
PERSONA_FACET_LABELS = (
    "PersonaSummary",
    "ExpressionStyleTrait",
    "VerbalTicObservation",
    "MbtiHypothesisFacet",
    "DialogueExemplar",
    "PersonaAnalysisMeta",
    "EmotionDimensionObservation",
    "SocialRelationSketchFacet",
    "EnneagramHypothesisFacet",
    "BigFiveSketchFacet",
    "BigFiveTraitFacet",
    "SalientTraitObservation",
)

FACET_SCHEMA_VERSION = "wx_persona_graph_v4"

_MBTI_CODE_RE = re.compile(
    r"\b([IE][NS][FT][JP]|INFP|INTJ|INFJ|INTP|ENFP|ENTJ|ENFJ|ENTP|"
    r"ISFP|ISTJ|ISFJ|ISTP|ESFP|ESTJ|ESFJ|ESTP)\b",
    re.IGNORECASE,
)

_LEVEL_MAP = {
    "low": "low",
    "mid": "medium",
    "medium": "medium",
    "high": "high",
    "unknown": "unknown",
    "low-mid": "medium",
    "mid-high": "medium",
}


def parse_analysis_meta(digest: dict[str, Any]) -> dict[str, Any]:
    raw = digest.get("analysis_meta_json") or "{}"
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        meta = {}
    return meta if isinstance(meta, dict) else {}


def inference_context(digest: dict[str, Any]) -> dict[str, Any]:
    """从 digest / analysis_meta 提取各 facet 共用的推断上下文。"""
    meta = parse_analysis_meta(digest)
    mode = str(meta.get("inference_mode") or "heuristic")
    llm_ok = mode == "heuristic+deepseek" and meta.get("llm_status") == "ok"
    return {
        "inference_mode": mode,
        "llm_provider": meta.get("llm_provider"),
        "llm_model": meta.get("llm_model"),
        "llm_status": meta.get("llm_status"),
        "heuristic_version": meta.get("heuristic_version", "wx_persona_v2"),
        "extractor_version": (
            str(meta.get("llm_model") or meta.get("heuristic_version") or FACET_SCHEMA_VERSION)
        )[:128],
        "default_inference_source": "deepseek" if llm_ok else "heuristic",
    }


def extract_mbti_type_code(text: str) -> str | None:
    if not text:
        return None
    m = _MBTI_CODE_RE.search(text)
    if not m:
        return None
    return m.group(1).upper()


def normalize_trait_level(raw: Any) -> str:
    key = str(raw or "unknown").strip().lower()
    return _LEVEL_MAP.get(key, "unknown")


def _facet_base(batch_id: str, ctx: dict[str, Any], *, inference_source: str, extractor: str | None = None) -> dict[str, Any]:
    return {
        "facet_id": str(uuid.uuid4()),
        "batch_id": batch_id,
        "schema_ver": FACET_SCHEMA_VERSION,
        "extractor": (extractor or ctx["extractor_version"])[:128],
        "imode": ctx["inference_mode"],
        "isrc": inference_source,
    }


def delete_old_persona_batch(tx: Any, batch_id: str) -> None:
    label_union = " OR ".join(f"x:{lb}" for lb in PERSONA_FACET_LABELS)
    tx.run(
        f"""
        MATCH (x)
        WHERE x.persona_batch_id = $bid AND ({label_union})
        DETACH DELETE x
        """,
        bid=batch_id,
    )


def _merge_person_node(tx: Any, *, person_key: str, display_name: str) -> None:
    """``person_key`` 为 wx-cli 根 ``username``（wxid）或本机 ``WX_LOCAL_USERNAME``。"""
    uname = (person_key or "").strip()[:128]
    dn = (display_name or "").strip()[:256] or uname
    tx.run(
        """
        OPTIONAL MATCH (legacy:Person {subject_id: $uname})
        WHERE legacy.username IS NULL
        SET legacy.username = $uname
        WITH 1 AS _
        MERGE (p:Person {username: $uname})
        ON CREATE SET p.created_at = datetime(), p.subject_id = $uname
        SET p.updated_at = datetime(),
            p.username = $uname,
            p.subject_id = $uname,
            p.display_name = CASE
              WHEN $dn <> '' THEN $dn
              ELSE coalesce(p.display_name, $uname)
            END
        """,
        uname=uname,
        dn=dn,
    )


def merge_person_shell(
    tx: Any,
    *,
    subject_id: str,
    display_name: str,
) -> None:
    """仅确保 Person 节点存在并更新展示名（不触碰 last_persona_batch_id，除非后续写入子图）。"""
    _merge_person_node(tx, person_key=subject_id, display_name=display_name)


def write_conversation_peer_links(
    tx: Any,
    *,
    subject_id_a: str,
    subject_id_b: str,
    batch_id: str,
    chat_session: str,
    sender_a_display: str,
    sender_b_display: str,
    relationship: dict[str, Any] | None = None,
) -> None:
    """在两人 Person 间建立双向 CONVERSATION_WITH（同一对多次导入会 MERGE 更新边上元数据）。"""
    if not subject_id_a or not subject_id_b or subject_id_a == subject_id_b:
        return
    chat = (chat_session or "")[:256]
    sa = (sender_a_display or "")[:128]
    sb = (sender_b_display or "")[:128]
    rel = relationship if isinstance(relationship, dict) else {}
    rel_type = str(rel.get("type") or "unknown")[:48]
    rel_zh = str(rel.get("type_zh") or "不确定")[:32]
    rel_conf = float(rel.get("confidence", 0.0) or 0.0)
    rel_rationale = str(rel.get("rationale") or "")[:512]
    rel_src = str(rel.get("inference_source") or "heuristic")[:32]
    for src_sid, tgt_sid, peer_lab in (
        (subject_id_a, subject_id_b, sb),
        (subject_id_b, subject_id_a, sa),
    ):
        tx.run(
            """
            MATCH (a:Person) WHERE a.username = $sa OR a.subject_id = $sa
            MATCH (b:Person) WHERE b.username = $sb OR b.subject_id = $sb
            MERGE (a)-[r:CONVERSATION_WITH]->(b)
            SET r.updated_at = datetime(),
                r.persona_batch_id = $batch_id,
                r.chat_session = $chat,
                r.peer_sender_label = $peer_lab,
                r.counterpart_subject_id = $sb,
                r.relationship_type = $rel_type,
                r.relationship_type_zh = $rel_zh,
                r.relationship_confidence = $rel_conf,
                r.relationship_rationale = $rel_rationale,
                r.relationship_inference_source = $rel_src
            """,
            sa=src_sid,
            sb=tgt_sid,
            batch_id=batch_id,
            chat=chat,
            peer_lab=peer_lab,
            rel_type=rel_type,
            rel_zh=rel_zh,
            rel_conf=rel_conf,
            rel_rationale=rel_rationale,
            rel_src=rel_src,
        )


def write_persona_facet_graph(
    tx: Any,
    *,
    subject_id: str,
    batch_id: str,
    display_name: str,
    fallback_display: str,
    digest: dict[str, Any],
    persona_summary: str,
) -> int:
    """在同一事务内写入 Person 及整批特质子图，返回 facet 节点数。"""
    ctx = inference_context(digest)
    src_default = ctx["default_inference_source"]
    created = 0

    mbti_code = digest.get("mbti_type_code") or extract_mbti_type_code(
        str(digest.get("mbti_hypothesis") or "")
    )
    meta = parse_analysis_meta(digest)
    chat_session = str(meta.get("chat") or "")[:200]
    profiled_label = str(meta.get("profiled_speaker_label") or "")[:128]
    me_label = str(meta.get("wx_me_sender_label") or "")[:128]

    tx.run(
        """
        OPTIONAL MATCH (legacy:Person {subject_id: $subject_id})
        WHERE legacy.username IS NULL
        SET legacy.username = $subject_id
        WITH 1 AS _
        MERGE (p:Person {username: $subject_id})
        ON CREATE SET p.created_at = datetime(), p.subject_id = $subject_id
        SET p.updated_at = datetime(),
            p.username = $subject_id,
            p.subject_id = $subject_id,
            p.display_name = CASE
              WHEN $display_name <> '' THEN $display_name
              ELSE coalesce(p.display_name, $fallback_display)
            END,
            p.last_persona_batch_id = $batch_id,
            p.last_persona_analyzed_at = datetime(),
            p.persona_analysis_version = $persona_version,
            p.last_inference_mode = $inference_mode,
            p.last_mbti_type_code = $mbti_code,
            p.chat_session_label = $chat_session,
            p.profiled_speaker_label = $profiled_label,
            p.wx_me_sender_label = $me_label,
            p.persona_summary = null,
            p.expression_style = null,
            p.verbal_tics_json = null,
            p.mbti_hypothesis = null,
            p.interaction_samples_json = null,
            p.persona_analysis_meta_json = null
        """,
        subject_id=subject_id,
        display_name=display_name,
        fallback_display=fallback_display,
        batch_id=batch_id,
        persona_version=FACET_SCHEMA_VERSION,
        inference_mode=ctx["inference_mode"],
        mbti_code=mbti_code,
        chat_session=chat_session,
        profiled_label=profiled_label,
        me_label=me_label,
    )

    base = _facet_base(batch_id, ctx, inference_source=src_default)
    tx.run(
        """
        MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
        CREATE (s:PersonaSummary {
          facet_id: $facet_id,
          persona_batch_id: $batch_id,
          facet_schema_version: $schema_ver,
          extractor_version: $extractor,
          inference_mode: $imode,
          inference_source: $isrc,
          text: $text,
          analysis_version: $schema_ver,
          created_at: datetime()
        })
        CREATE (p)-[:HAS_PERSONA_SUMMARY]->(s)
        """,
        subject_id=subject_id,
        text=persona_summary[:4000],
        **base,
    )
    created += 1

    base = _facet_base(batch_id, ctx, inference_source=src_default)
    tx.run(
        """
        MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
        CREATE (e:ExpressionStyleTrait {
          facet_id: $facet_id,
          persona_batch_id: $batch_id,
          facet_schema_version: $schema_ver,
          extractor_version: $extractor,
          inference_mode: $imode,
          inference_source: $isrc,
          description: $desc,
          created_at: datetime()
        })
        CREATE (p)-[:HAS_EXPRESSION_STYLE]->(e)
        """,
        subject_id=subject_id,
        desc=digest["expression_style"][:1024],
        **base,
    )
    created += 1

    for tic in digest.get("verbal_tics_list") or []:
        base = _facet_base(
            batch_id, ctx, inference_source="heuristic", extractor=ctx["heuristic_version"]
        )
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (t:VerbalTicObservation {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              pattern_label: $label,
              hit_count: $cnt,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_VERBAL_TIC]->(t)
            """,
            subject_id=subject_id,
            label=str(tic.get("name", ""))[:128],
            cnt=int(tic.get("count", 0)),
            **base,
        )
        created += 1

    for ed in digest.get("emotion_dimensions") or []:
        if not isinstance(ed, dict):
            continue
        method = str(ed.get("method", ""))
        isrc = "deepseek" if method.startswith("deepseek") else "heuristic"
        if method.startswith("lexicon+deepseek"):
            isrc = "hybrid"
        ext = ctx["extractor_version"] if isrc != "heuristic" else ctx["heuristic_version"]
        base = _facet_base(batch_id, ctx, inference_source=isrc, extractor=ext)
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (emo:EmotionDimensionObservation {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              dimension: $dim,
              lexical_hits: $hits,
              score_0_1: $score,
              method: $method,
              caution: $caution,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_EMOTION_DIMENSION]->(emo)
            """,
            subject_id=subject_id,
            dim=str(ed.get("dimension", ""))[:128],
            hits=int(ed.get("lexical_hits", 0) or 0),
            score=float(ed.get("score_0_1", 0.0) or 0.0),
            method=method[:256],
            caution=str(ed.get("caution", ""))[:512],
            **base,
        )
        created += 1

    for st in digest.get("salient_trait_observations") or []:
        if not isinstance(st, dict):
            continue
        base = _facet_base(batch_id, ctx, inference_source="deepseek", extractor=ctx["extractor_version"])
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (st:SalientTraitObservation {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              trait_key: $trait_key,
              category: $category,
              label: $label,
              narrative: $narrative,
              episode_summary: $episode_summary,
              supporting_cues: $supporting_cues,
              salience_0_1: $salience,
              method: $method,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_SALIENT_TRAIT]->(st)
            """,
            subject_id=subject_id,
            trait_key=str(st.get("trait_key", ""))[:96],
            category=str(st.get("category", "other"))[:48],
            label=str(st.get("label", ""))[:160],
            narrative=str(st.get("narrative", ""))[:900],
            episode_summary=str(st.get("episode_summary", ""))[:420],
            supporting_cues=str(st.get("supporting_cues", ""))[:360],
            salience=float(st.get("salience_0_1", 0.0) or 0.0),
            method=str(st.get("method", "deepseek_persona_review_v1"))[:128],
            **base,
        )
        created += 1

    sk = digest.get("social_relation_sketch") or {}
    if isinstance(sk, dict) and sk:
        interp_src = str(sk.get("interpretation_source") or src_default)
        base = _facet_base(batch_id, ctx, inference_source="hybrid")
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (sr:SocialRelationSketchFacet {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              channel: $channel,
              session_label: $session_label,
              distinct_peer_senders: $dps,
              turns_self: $ts,
              turns_peer: $tp,
              turns_anonymous_sender: $ta,
              self_turn_ratio: $stratio,
              interpretation: $interp,
              interpretation_source: $interp_src,
              dyadic_relation_type: $drel_type,
              dyadic_relation_type_zh: $drel_zh,
              dyadic_relation_confidence: $drel_conf,
              dyadic_relation_rationale: $drel_rat,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_SOCIAL_RELATION_SKETCH]->(sr)
            """,
            subject_id=subject_id,
            channel=str(sk.get("channel", ""))[:64],
            session_label=str(sk.get("session_label", ""))[:256],
            dps=int(sk.get("distinct_peer_senders", 0) or 0),
            ts=int(sk.get("turns_self", 0) or 0),
            tp=int(sk.get("turns_peer", 0) or 0),
            ta=int(sk.get("turns_anonymous_sender", 0) or 0),
            stratio=float(sk.get("self_turn_ratio", 0.0) or 0.0),
            interp=str(sk.get("interpretation", ""))[:512],
            interp_src=interp_src[:32],
            drel_type=str(sk.get("dyadic_relation_type") or "")[:48] or None,
            drel_zh=str(sk.get("dyadic_relation_type_zh") or "")[:32] or None,
            drel_conf=float(sk.get("dyadic_relation_confidence", 0.0) or 0.0),
            drel_rat=str(sk.get("dyadic_relation_rationale") or "")[:512] or None,
            **base,
        )
        created += 1

    ennea = digest.get("enneagram_hypothesis") or {}
    if isinstance(ennea, dict) and ennea:
        en_src = str(ennea.get("source", "placeholder"))
        isrc = "deepseek" if en_src == "deepseek" else "heuristic"
        status = str(ennea.get("status") or ("llm_hypothesis" if isrc == "deepseek" else "placeholder"))
        ext = ctx["extractor_version"] if isrc == "deepseek" else ctx["heuristic_version"]
        base = _facet_base(batch_id, ctx, inference_source=isrc, extractor=ext)
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (en:EnneagramHypothesisFacet {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              type_guess: $tg,
              wing_guess: $wg,
              confidence: $conf,
              hypothesis_text: $htxt,
              source: $src,
              status: $status,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_ENNEAGRAM_HYPOTHESIS]->(en)
            """,
            subject_id=subject_id,
            tg=str(ennea.get("type_guess", ""))[:32],
            wg=str(ennea.get("wing_guess", ""))[:32],
            conf=float(ennea.get("confidence", 0.0) or 0.0),
            htxt=str(ennea.get("hypothesis_text", ""))[:900],
            src=en_src[:64],
            status=status[:32],
            **base,
        )
        created += 1

    big5 = digest.get("big_five_lexical_sketch") or []
    if isinstance(big5, list):
        for trait_row in big5:
            if not isinstance(trait_row, dict):
                continue
            method = str(trait_row.get("method", "zh_lexicon_v1"))
            isrc = "hybrid" if "deepseek" in method else "heuristic"
            ext = ctx["extractor_version"] if isrc != "heuristic" else ctx["heuristic_version"]
            base = _facet_base(batch_id, ctx, inference_source=isrc, extractor=ext)
            trait_name = str(trait_row.get("trait", "")).replace("_proxy", "")[:64]
            tx.run(
                """
                MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
                CREATE (bf:BigFiveTraitFacet {
                  facet_id: $facet_id,
                  persona_batch_id: $batch_id,
                  facet_schema_version: $schema_ver,
                  extractor_version: $extractor,
                  inference_mode: $imode,
                  inference_source: $isrc,
                  trait: $trait,
                  model: 'Big5',
                  level: $level,
                  lexical_hits: $hits,
                  note: $note,
                  method: $method,
                  created_at: datetime()
                })
                CREATE (p)-[:HAS_BIG_FIVE_TRAIT]->(bf)
                """,
                subject_id=subject_id,
                trait=trait_name,
                level=normalize_trait_level(trait_row.get("level")),
                hits=int(trait_row.get("lexical_hits", 0) or 0),
                note=str(trait_row.get("note", ""))[:512],
                method=method[:64],
                **base,
            )
            created += 1

    mbti_status = str(digest.get("mbti_status") or "placeholder")
    mbti_isrc = "deepseek" if mbti_status == "llm_hypothesis" else "heuristic"
    ext = ctx["extractor_version"] if mbti_isrc == "deepseek" else ctx["heuristic_version"]
    base = _facet_base(batch_id, ctx, inference_source=mbti_isrc, extractor=ext)
    tx.run(
        """
        MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
        CREATE (m:MbtiHypothesisFacet {
          facet_id: $facet_id,
          persona_batch_id: $batch_id,
          facet_schema_version: $schema_ver,
          extractor_version: $extractor,
          inference_mode: $imode,
          inference_source: $isrc,
          type_code: $type_code,
          hypothesis_text: $txt,
          literature_note: $lit,
          status: $status,
          confidence: $conf,
          llm_provider: $llm_provider,
          created_at: datetime()
        })
        CREATE (p)-[:HAS_MBTI_HYPOTHESIS]->(m)
        """,
        subject_id=subject_id,
        type_code=mbti_code,
        txt=digest["mbti_hypothesis"][:900],
        lit=(digest.get("mbti_literature_note") or "")[:900],
        status=mbti_status[:32],
        conf=float(digest.get("mbti_confidence", 0.0) or 0.0),
        llm_provider=(ctx.get("llm_provider") or "")[:32] or None,
        **base,
    )
    created += 1

    meta = parse_analysis_meta(digest)
    base = _facet_base(batch_id, ctx, inference_source=src_default)
    tx.run(
        """
        MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
        CREATE (meta:PersonaAnalysisMeta {
          facet_id: $facet_id,
          persona_batch_id: $batch_id,
          facet_schema_version: $schema_ver,
          extractor_version: $extractor,
          inference_mode: $imode,
          inference_source: $isrc,
          llm_provider: $llm_provider,
          llm_model: $llm_model,
          llm_status: $llm_status,
          heuristic_version: $heuristic_version,
          payload_json: $json,
          created_at: datetime()
        })
        CREATE (p)-[:HAS_PERSONA_ANALYSIS_META]->(meta)
        """,
        subject_id=subject_id,
        json=digest["analysis_meta_json"][:8000],
        llm_provider=meta.get("llm_provider"),
        llm_model=meta.get("llm_model"),
        llm_status=meta.get("llm_status"),
        heuristic_version=meta.get("heuristic_version"),
        **base,
    )
    created += 1

    for idx, thread in enumerate(digest.get("exemplar_threads") or []):
        base = _facet_base(
            batch_id, ctx, inference_source="heuristic", extractor=ctx["heuristic_version"]
        )
        tx.run(
            """
            MATCH (p:Person) WHERE p.username = $subject_id OR p.subject_id = $subject_id
            CREATE (d:DialogueExemplar {
              facet_id: $facet_id,
              persona_batch_id: $batch_id,
              facet_schema_version: $schema_ver,
              extractor_version: $extractor,
              inference_mode: $imode,
              inference_source: $isrc,
              order_index: $ord,
              turns_json: $turns,
              created_at: datetime()
            })
            CREATE (p)-[:HAS_DIALOGUE_EXEMPLAR]->(d)
            """,
            subject_id=subject_id,
            ord=idx,
            turns=json.dumps(thread, ensure_ascii=False)[:8000],
            **base,
        )
        created += 1

    return created
