# 人格本体图（Personality Ontology Graph, POG）项目简报

**版本**：0.2（文档先行）  
**技术栈规划**：Neo4j · Python 后端 · Vue 前端  
**定位**：心理学 × 知识图谱 × 生成式 AI 的**可演进基层数据与推理层**（非单一黑盒模型）

**文档索引**


| 文档                                                                     | 用途                                           |
| ---------------------------------------------------------------------- | -------------------------------------------- |
| [PITCH_ONE_PAGER.md](PITCH_ONE_PAGER.md)                               | 答辩一页纸（约 1 分钟口播结构）                            |
| [TECH_SPEC.md](TECH_SPEC.md)                                           | API、幂等、Neo4j 约束、验收清单                         |
| [WECHAT_WX_CLI.md](WECHAT_WX_CLI.md)                                   | 本机 wx-cli 导出 JSON → `POST /api/v1/ingest` 流程 |
| [../ontology/backend/ONTOLOGY.yaml](../ontology/backend/ONTOLOGY.yaml) | TBox 字段级定义与 Neo4j 映射（语义真源）                   |


---

## 1. 一句话与核心价值

构建一套**可解释、可版本化、可合并增量证据**的「人格—社会情境—交互事件」本体与图数据库，把聊天记录、自述、行为日志等多模态输入，经抽取与对齐后写入 Neo4j；在此之上做**人格近似、情境推演、干预路径仿真**，为心理科技、数字孪生人格、合规培训等场景提供**结构化底座**。

**与纯 LLM「端到端猜人格」的差异**：图数据库固化**关系结构与时间轴**，本体约束**语义一致性**，便于审计、复现与产品化迭代。

---

## 2. 创新性（评委视角可讲清楚的点）


| 维度       | 说明                                                                                          |
| -------- | ------------------------------------------------------------------------------------------- |
| **表示创新** | 人格不只是一组标签向量，而是「自我节点 + 社会身份 + 关系边 + 事件时间线 + 证据引用」的**可查询图**，支持因果链与反事实查询（若某关系强度变化，对行为倾向的敏感分析）。 |
| **工程创新** | 本体（TBox）与实例（ABox）分离：Schema 可演进；同一用户多数据源**实体对齐**后合并，避免「每个 chat 一个孤立画像」。                      |
| **方法创新** | LLM/多模态模型负责**抽取与假设生成**，图与规则负责**校验、冲突解决、置信度传播**；形成「生成—约束—反馈」闭环。                              |
| **商业创新** | 可拆成 **B2B API（图谱写入/查询）**、**B2B2C 插件（咨询/教练工作台）**、**企业合规场景（反钓鱼意识、沟通风格训练）**，数据驻留与权限模型清晰。       |


---

## 3. 学术与技术依据（联网检索摘要）

以下方向表明「本体 / 知识图谱 + 文本 / 心理语言学特征 → 人格相关推断」在学界已有积累，本项目将其**落到可运营的图数据产品形态**。

1. **基于知识图谱辅助的文本人格预测**
  例如 PMC 上关于利用知识图谱增强文本自动人格预测的研究（概念与外部知识对齐、图结构特征与分类器结合等思路）。  
   参考：[Knowledge Graph-Enabled Text-Based Automatic Personality Prediction (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9236841/)
2. **人格知识图谱（Personality KG）**
  IEEE 等工作提出面向人格分析的知识图谱构建与利用（如 PerKG 等脉络），强调**结构化先验**与下游任务结合。  
   参考：[PerKG: A Personality Knowledge Graph for Personality Analysis (IEEE Xplore)](https://ieeexplore.ieee.org/document/9945152/)
3. **本体网络支持人格特质/层面推断**
  IEEE 上关于构建本体网络以支持人格特质与层面推断的会议论文，对应本项目「TBox 定义 + 推理」路线。  
   参考：[Creating an Ontological Networks to Support the Inference of Personality Traits and Facets (IEEE Xplore)](https://ieeexplore.ieee.org/document/8526453/)
4. **社交网络图结构与人格**
  研究表明大五等人格特质与**自我中心网络结构**（ tie 强度、三元组结构等）存在统计关联，为「关系图 + 人格」提供心理学侧支撑。  
   参考：*Personalized networks? How the Big Five personality traits influence the structure of egocentric networks*（ScienceDirect 条目页）
5. **图数据库实践范例**
  Neo4j 社区 GraphGist 中有基于图模式分析社交媒体行为/人格相关预测思路的示例，可借鉴**节点—关系—图算法**表达方式。  
   参考：[Personality Prediction based on Pattern Analysis on Social Media (Neo4j GraphGists)](https://neo4j.com/graphgists/personality-prediction-based-on-pattern-analysis-on-social-media-2/)

> **说明**：黑客松阶段不必复现论文 SOTA，而需讲清「为何用图 + 本体」以及 **MVP 可演示路径**。

---

## 4. 「本体论 Ontology」在本项目中的确切含义

避免哲学词泛化，建议在答辩与文档中严格区分：

- **哲学本体论**：存在与实在的讨论 — 产品层面仅作**隐喻背书**，不宜展开。  
- **信息科学本体（Ontology）**：领域概念的形式化规范 — **本项目核心**：类、属性、关系、约束、同义词、与外部标准（如心理测量维度）的映射。  
- **知识图谱（KG）**：本体 + 实例数据 + 运维 — **Neo4j** 承担存储与查询；**RDF/OWL** 可选作交换格式，非必须第一版。

**落地原则**：先用 **Neo4j 标签 + 关系类型 + 属性** 实现 80% 本体约束；若需复杂推理再引入 OWL 推理机或规则引擎。

---

## 5. 商业可行性与场景（合规优先）

### 5.1 可付费客户画像

- **EAP / 心理咨询机构 / 教练**：个案材料多源整理、会谈前后「假设—证据」结构化（需执业边界与知情同意）。  
- **企业安全与合规培训**：钓鱼与社工防护演练中的**角色与话术压力点**建模（强调**防御与意识提升**，禁止攻击性用途）。  
- **游戏 / 社交产品**：NPC 人格一致性、剧情分支与「关系记忆」——图天然适合。  
- **科研合作**：纵向研究中的关系与事件编码（匿名化数据集）。

### 5.2 商业模式草案

- **SaaS**：按「活跃人格档案数 / API 调用 / 存储 GB」计费。  
- **私有化部署**：金融、政务、医院场景。  
- **数据增值服务**（远期）：仅聚合匿名统计与模型，不出售可识别个人图谱。

### 5.3 关于「社会工程 + AI」表述的边界（强烈建议写进路演）

公开材料中建议将「社会工程」收窄为：

- **社会动力学 / 互动策略仿真**（谈判、管理沟通、客服冲突降级）；或  
- **网络安全语境下的社工防御演练**（红队授权、范围限定、审计日志）。

并在文档与演示中明确 **禁止**：未经授权对他人画像、钓鱼、欺诈话术生成等违法或不道德用途。这既是伦理要求，也有助于评委与投资人信任。

---

## 6. 系统架构（规划）

```
[多模态导入] 聊天记录 / 文档 / 音频转写 / 量表
        ↓
[抽取与对齐服务] Python：解析 → NER/关系抽取 → LLM 结构化 JSON
        ↓
[本体校验与融合] 规则 + 置信度 + 冲突解决（同一实体合并）
        ↓
[Neo4j 写入] Cypher / py2neo / neo4j-driver
        ↓
[推理与仿真层] 图算法 + 可选 GNN / 与 LLM 的检索增强（GraphRAG）
        ↓
[Vue 前端] 图可视化（如 neovis.js / G6 / Cytoscape.js）+ 时间轴 + 证据面板
```

**关键中间件**：任务队列（Celery / RQ）、对象存储（原始文件）、向量库（可选，用于语义检索与对齐）。

---

## 7. 图数据模型草案（Neo4j）

以下为 **MVP 级** 节点与关系类型命名建议（可在实现期微调）。

### 7.1 核心节点（标签）


| 标签                    | 含义                   | 关键属性示例                                          |
| --------------------- | -------------------- | ----------------------------------------------- |
| `:Person`             | 自然人或「被建模自我」          | `subject_id`, `display_name`, `created_at`      |
| `:Persona`            | 面向某应用场景的人格切片（同一人的多面） | `scenario`, `version`                           |
| `:SocialIdentity`     | 社会身份（职业、家庭角色、社群标签）   | `role_name`, `institution`, `valid_from`        |
| `:Agent`              | 对话中的他者（真实人或 bot）     | `agent_type`                                    |
| `:Interaction`        | 一次可定位的交互事件           | `channel`, `timestamp`, `summary`               |
| `:Utterance`          | 话语/消息单元              | `text`, `lang`, `embedding_id`                  |
| `:TraitHypothesis`    | 对特质的假设节点（非事实表）       | `model`（如 Big5）, `facet`, `score`, `confidence` |
| `:Evidence`           | 指向原文的证据              | `source_uri`, `span`, `extractor_version`       |
| `:Goal` / `:Stressor` | 目标与压力源（干预与推演用）       | `description`, `severity`                       |


### 7.2 核心关系（类型）

- `(Person)-[:HAS_IDENTITY]->(SocialIdentity)`  
- `(Person)-[:INTERACTED_IN]->(Interaction)-[:WITH]->(Agent)`  
- `(Interaction)-[:CONTAINS]->(Utterance)`  
- `(TraitHypothesis)-[:SUPPORTED_BY]->(Evidence)-[:ANCHORED_AT]->(Utterance)`  
- `(Person)-[:RELATED_TO {type, strength, sentiment}]->(Agent)`  
- `(Persona)-[:REFINES]->(Person)` — 多场景人格切片

**设计要点**：把「人格结论」做成 `**TraitHypothesis` 节点**而非仅属性，便于多模型并存、版本对比与撤回。

---

## 8. 本体（TBox）层建议

- **顶层类**：`Agent`, `Event`, `Proposition`, `PsychologicalConstruct`, `Measurement`.  
- **关系定义**：域、值域、基数（如每人同一时间至多一个「当前默认 Persona」可通过约束或应用层保证）。  
- **与外部对齐**：Big Five、价值观量表等用 `**owl:sameAs` 等价映射表**（可先 JSON 配置）。  
- **时间本体**：所有事件与关系带 `valid_from` / `valid_to`，支持「当时的自我」查询。

可选技术：**OWLReady2**、**Protégé** 导出 Turtle，再映射到 Neo4j；黑客松 MVP 可用 **YAML 本体清单** 代替。

---

## 9. Python 后端模块划分（后续实现）


| 模块         | 职责                               |
| ---------- | -------------------------------- |
| `ingest`   | 文件上传、解析、脱敏                       |
| `extract`  | LLM prompt、schema 约束 JSON、降级规则抽取 |
| `ontology` | 校验、归一化、同义词、版本号                   |
| `graph`    | Neo4j 事务写入、幂等键、合并策略              |
| `query`    | 固定 Cypher 模板 + GraphRAG 检索接口     |
| `simulate` | 简单反事实：边权重编辑 + LLM 叙述生成（与图路径绑定）   |


**API 形态**：OpenAPI / FastAPI；鉴权 OAuth2 或 API Key（演示版可简化）。

---

## 10. Vue 前端信息架构（后续实现）

- **档案列表** → **人格档案详情**（图 + 时间轴双视图）  
- **导入向导**（数据源、同意声明、预览三元组）  
- **假设面板**（TraitHypothesis 列表、置信度、证据跳转）  
- **推演实验室**（参数滑块：关系强度 / 压力事件 → 生成叙事 + 图 diff）

---

## 11. 「无限逼近」的务实定义

答辩中建议改为 **「证据一致下的贝叶斯式逼近」**：

- 每条假设绑定 **Evidence** 与 **confidence**；  
- 新数据仅做 **局部更新** 与 **冲突记录**，而非覆盖式重写；  
- 对外输出区分 **观测层**（事实交互）与 **推断层**（假设节点）。

这既诚实又符合工程可扩展性。

---

## 12. MVP（黑客松可交付）范围建议

**必须（P0）**

- Neo4j：上述核心节点/关系的 **Schema + 示例数据集**（虚构人物，禁止真实他人隐私）。  
- Python：**单源**（如微信导出 JSON 或纯文本）→ 抽取 → 写入 → 2～3 个固定查询（如「与 A 的冲突事件链」「外向相关假设及证据」）。  
- Vue：**一张可交互图** + **证据侧栏**。

**可选（P1）**

- 简单 GraphRAG：子图检索 + LLM 生成「人格摘要（带引用）」。  
- 多 Persona 切换演示。

**不做（本期刻意砍掉）**

- 临床诊断级效度验证、真实用户大规模部署、医疗声明。

---

## 13. 风险与对策


| 风险                   | 对策                        |
| -------------------- | ------------------------- |
| 幻觉抽取                 | 证据节点强制锚定；低置信度不入主视图        |
| 隐私与合规                | 本地化 Neo4j、加密、访问审计、演示全虚构数据 |
| 评委质疑「和 ChatGPT 有何不同」 | 强调**结构化记忆、可查询关系史、版本化假设**  |
| 本体过重拖进度              | TBox 用 YAML，复杂推理后移        |


---

## 14. 后续文档与代码目录建议（创建代码时）

```
Ontology/
├── docs/
│   ├── PROJECT_BRIEF.md          # 本文（总览）
│   ├── PITCH_ONE_PAGER.md
│   ├── TECH_SPEC.md
│   └── ETHICS_AND_DATA.md
├── backend/                      # FastAPI + workers
├── frontend/                     # Vue 3
├── ontology/
│   └── ONTOLOGY.yaml             # TBox 草案（已实现）
└── docker-compose.yml            # Neo4j + api + web
```

---

## 15. 结语（路演可用）

本项目把「人格」从黑盒分数，升级为**可审计的图结构 + 本体约束 + 增量证据**，对齐心理学与知识图谱领域已有研究方向，并以 Neo4j + Python + Vue 走通**导入—建模—查询—叙事化解释**的闭环。第一阶段聚焦 **合规场景与虚构演示数据**，为后续心理科技与企业培训产品化预留接口与计费锚点。

---

*文档随实现迭代；实现阶段请同步补充 `docs/API.md`（OpenAPI 导出或手写），并随数据模型演进 bump `ontology/ONTOLOGY.yaml` 中的 `meta.schema_version`。*