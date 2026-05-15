# 从对话文本推断人格/情绪：研究与使用边界（POG 参考）

本页汇总与「微信/聊天文本 → 人格、情绪、MBTI、九型」相关的**研究取向与局限**，供产品与后续 LLM/量表管线对齐；**不构成临床或职业测评结论**。

## 1. 文本与性格（短信 / 即时通讯语境）

- Holtgraves, T. (2011). *Text messaging, personality, and the social context*. Journal of Research in Personality, 45(6), 668–676.  
  - 链接：<https://www.sciencedirect.com/science/article/abs/pii/S0092656610001698>  
  - 要点：短信语言与性格、**关系语境**相关；缩写与风格随人格与对象变化。提示我们：社会关系维度在模型中应显式存在。

## 2. 自然语言处理与人格（综述与实践）

- *Text speaks louder: Insights into personality from natural language processing*（PLOS ONE, 2025 附近工作流综述类文章，见期刊页）。  
  - 链接：<https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0323096>  
  - 要点：大五等人格维度与语言特征更可对接；**标签式类型学**（如 MBTI）在数据与偏置上需格外谨慎。

## 3. 从文本预测 MBTI 的难度（NLP 会议论文）

- EACL 2021 相关工作指出：社交媒体 MBTI 预测中，强基线外提升有限，且 MBTI 与**语言学表征**的理论对齐弱于大五等维度模型。  
  - 示例条目：<https://aclanthology.org/2021.eacl-main.312.pdf>  

## 4. 即时通讯与人格特征（应用向）

- Springer 章节：*Prediction of Selected Personality Traits Based on Text Messages from Instant Messenger*（LNCS 卷内章节，见 Springer 页面）。  
  - 链接：<https://link.springer.com/chapter/10.1007/978-3-030-48256-5_66>  

## 5. 九型人格（Enneagram）

- 九型多依赖**自陈量表、访谈与长期自我观察**；从短对话**机械定号**缺乏常模与效度链。POG 中 `EnneagramHypothesisFacet` 默认 **占位 + 低置信度**，待接入量表或专家标注后再写结论。

## 7. 人格描述的多层级（超越「类型标签」）

- McAdams, D. P. (1995). *What do we know when we know a person?* Journal of Personality, 63(3), 365–396.  
  - 链接：<https://doi.org/10.1111/j.1467-6494.1995.tb00500.x>  
  - 要点：**第一层**宽泛特质；**第二层**情境化的个人关切、目标、防御与策略；**第三层**叙事认同（整合过去—现在—未来的生命故事）。即时通讯短样本更适合产出第二层线索与**谨慎的叙事主题**，不宜把聊天风格直接等同于稳定特质或诊断。

## 8. 人际与表达的组织框架（非诊断）

- 人际环状模型（Interpersonal Circumplex）将人际行为组织在 **agency（支配—顺从）** 与 **communion（冷漠—热情）** 等轴上，常用于理解互动风格；从文本推断仍属假设，需结合关系角色与语境。  
  - 综述入口示例：Gurtman, M. B. (2009). *Interpersonal circumplex*. In P. J. Corr & G. Matthews (Eds.), *The Cambridge handbook of personality psychology* (pp. 347–369). Cambridge University Press.

## 9. 与本项目 LLM 管线对齐

- DeepSeek 提示词版本见 `llm_prompt_version`（如 `pog_deepseek_review_v1`）：要求显式**评审协议**（证据范围、对立假设、局限、伦理边界）、**显著可观察特质**列表（可含脱敏 `episode_summary`），并保留对大五/MBTI/九型的弱假设定位。图数据库写入见 `SalientTraitObservation` 节点（`wx_persona_graph_v4` 起）。

---

*实现：`backend/app/ingest/wx_persona.py`（启发式）、`backend/app/llm/persona_llm.py`（DeepSeek 评审式增强）、`backend/app/ingest/wx_cli.py`（写入 Neo4j 特质子图）。后续可替换为文献驱动的特征工程 + LLM + 量表融合管线。*
