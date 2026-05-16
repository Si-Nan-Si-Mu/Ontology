# POG 技术规格书（v0.1）

本文与 `ontology/ONTOLOGY.yaml` 同步；实现以 YAML 为**语义真源**，Neo4j 为**运行库**。

---

## 1. 技术栈


| 层    | 选型（默认）                                                 |
| ---- | ------------------------------------------------------ |
| 图库   | Neo4j 5.x（Community 可满足演示；生产考虑 Enterprise 与 RBAC）      |
| 后端   | Python 3.11+，FastAPI，Pydantic v2                       |
| 驱动   | `neo4j` 官方驱动（异步可选）                                     |
| 任务队列 | RQ 或 Celery（长耗时抽取）                                     |
| 前端   | Vue 3 + TypeScript，Vite；图可视化 neovis.js / @antv/g6（二选一） |
| LLM  | 可插拔（OpenAI 兼容 API / 本地）；抽取输出 **JSON Schema 强约束**       |


---

## 2. 逻辑架构

```
Client (Vue)
    │  HTTPS
    ▼
API Gateway (FastAPI)
    ├── /ingest      上传与任务创建
    ├── /jobs/{id}   任务状态
    ├── /persons     档案 CRUD（元数据）
    ├── /graph/query 参数化 Cypher 或预置查询 ID
    └── /narrate     可选 GraphRAG（子图 + LLM）
         │
         ├── Worker: parse → extract → validate → MERGE
         │
         ▼
Neo4j
```

---

## 3. 标识与幂等


| 概念            | 规则                                                                              |
| ------------- | ------------------------------------------------------------------------------- |
| `subject_id`  | 系统内 UUID；对外业务 ID 可映射                                                            |
| `Person` 节点   | `subject_id` **唯一约束**                                                           |
| `Interaction` | `interaction_key = hash(person_id, channel, start_ts, normalized_summary)` 可选唯一 |
| `Utterance`   | `utterance_key` 由 `(interaction_id, sequence)` 或内容哈希决定                          |
| `Evidence`    | `evidence_key` 由 `(extractor_version, anchor_ref)` 哈希，避免重复写入                    |


**合并策略**：同一 `Agent` 用 `canonical_name` + 可选 `alias[]` 归并；冲突写入 `:Conflict` 节点或 `Person.conflict_log`（实现期二选一，规格推荐独立 `Conflict` 节点便于查询）。

---

## 4. Neo4j 约束与索引（建议）

```cypher
// 示例：实现时按实际标签调整
CREATE CONSTRAINT person_subject IF NOT EXISTS
FOR (p:Person) REQUIRE p.subject_id IS UNIQUE;

CREATE INDEX interaction_ts IF NOT EXISTS
FOR (i:Interaction) ON (i.timestamp);

CREATE INDEX utterance_interaction IF NOT EXISTS
FOR (u:Utterance) ON (u.interaction_id);
```

全文索引（可选）：`Utterance.text` 便于演示搜索。

---

## 5. API 草案（REST）

路径前缀：`/api/v1`。以下字段名为示意。

### 5.1 `POST /ingest`（当前实现：`/api/v1/ingest`）

**Request**（`application/json`）：

- **必填**：`subject_id`（被本体化的 `Person` 锚点）。
- **可选**：`subject_display_name`、`note`。
- `**self_speaker_label`**：当 `source_type=wechat_export` 时**必填**，须与 wx-cli 导出 JSON 中每条消息的 `sender` 一致。
- `**raw_text`**：`plain_text` 时可空；`wechat_export` 时为 **wx-cli `wx export … --format json` 的完整 JSON 字符串**（根对象含 `messages`、`chat`、`is_group`）。
- `**source_type`**：`plain_text` | `wechat_export` | `other`（`plain_text` / `other` 当前为占位不落库；`wechat_export` 写入 Neo4j）。

**Response**：`plain_text` 等为占位 JSON；`wechat_export` 成功时含 `wx_cli.mode`（`persona_facet_graph`）、`facet_nodes_created`、`persona_batch_id` 等。

缺少或空白 `subject_id`，或 `wechat_export` 缺少正文 / `self_speaker_label` 时返回 **422**。JSON 非法或结构不符时返回 **400**。

`multipart` 文件上传为后续迭代。

### 5.1.1 本机 wx-cli（可选，`WX_CLI_ENABLED=true`）


| 方法   | 路径                                   | 说明                                                                                                            |
| ---- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| GET  | `/api/v1/wechat/status`              | 是否启用、`wx` 是否在 PATH 等                                                                                          |
| GET  | `/api/v1/wechat/sessions`            | 子进程 `wx sessions --json`，供前端选择会话                                                                              |
| POST | `/api/v1/wechat/preview-export`      | Body：`chat`、`probe_limit`；返回说话人频次与 `suggested_subject_id`                                                     |
| POST | `/api/v1/wechat/analyze-json`        | Body：`raw_text`；同上，不调用本机 `wx`                                                                                 |
| POST | `/api/v1/wechat/import-from-session` | Body：`subject_id`、`self_speaker_label`、`chat`（与导出所用会话名一致）、`limit` 等；内部 `wx export` → 与 `wechat_export` 相同写入逻辑 |


未启用时 `sessions` / `preview-export` / `import-from-session` 返回 **503**；`analyze-json` 不依赖 wx-cli，始终可用。仅建议在受信本机或内网部署使用。

### 5.2 `GET /jobs/{job_id}`

**Response**：`{ "status": "running|done|failed", "error": null, "stats": { "nodes_created": N } }`

### 5.3 `GET /api/v1/persons`（已实现）

返回库中全部 `Person` 锚点：`subject_id`、`display_name`、`last_persona_batch_id`、`last_persona_analyzed_at`、`element_id`。供前端下拉选择与开放接口页导出。

### 5.4 `GET /api/v1/person/{subject_id}/subgraph`（已实现）

返回指定 `Person` 的**外向**子图：`Person -[HAS_*]-> Facet` 的边列表及 facet 节点属性（JSON 安全化），供「图数据」页 SVG 可视化。不含全库扫描。

### 5.5 `GET /api/v1/person/{subject_id}/persona-export`（已实现）

Query：`format=json|text`。附件下载当前 `last_persona_batch_id` 下聚合的人格包。

### 5.6 `GET /api/v1/graph/nodes`（已实现）

分页列出全库任意标签节点（调试用）；与按 Person 子图查询互补。

### 5.7 `POST /graph/query`（内部或受控，P1）

仅允许**预置查询模板 ID** + 绑定参数，防止 Cypher 注入；黑客松后可改为 GraphQL/Data API。

**预置查询示例 ID**：


| `query_id`       | 说明                                       |
| ---------------- | ---------------------------------------- |
| `conflict_chain` | 某 `Person` 与指定 `Agent` 的高负面情绪交互路径        |
| `trait_evidence` | 某 `TraitHypothesis` 及 `SUPPORTED_BY` 证据树 |
| `timeline`       | 时间排序的 `Interaction` 列表                   |


### 5.8 `POST /narrate`（P1）

**Body**：`{ "subject_id", "locale", "max_evidence": 10 }`  
**流程**：子图检索 → 证据裁剪 → LLM 生成带 `[evidence_id]` 引用的 Markdown。

### 5.9 POG 第一层应用：以图库为 DeepSeek 的**严格**思考依据（规划）

**目标**：后续迭代中，面向「问答 / 解释 / 教练式回应」等能力时，**DeepSeek（或任意 OpenAI 兼容端点）的推理输入仅来自 Neo4j 已持久化事实**——以当前 MVP 写入为准：`Person` 锚点、`HAS_*` 连出的特质子图节点（如 `PersonaSummary`、`ExpressionStyleTrait`、`DialogueExemplar`、`PersonaAnalysisMeta` 等，见 `backend/ONTOLOGY.yaml`），以及导出包中已结构化的字段；**不得**把模型预训练常识当作该 `subject_id` 的个人事实写入回答正文（若缺图证据须显式标注为「图外常识」或「不确定」）。

**数据契约（服务端组装，不经用户随意拼 Cypher）**：

1. **读取**：以 `subject_id` + `last_persona_batch_id`（或等价批次锚点）为界，拉取与 `GET /api/v1/person/{subject_id}/subgraph` / `persona-export` 同源的**有界子图**（可额外限制边类型白名单与属性白名单，防注入与越权）。  
2. **裁剪**：按 token 预算做**确定性**裁剪（如按时间/显著性/节点类型优先级），并保留「被省略节点类型与数量」元数据写入 prompt，避免静默丢证据。  
3. **提示**：系统提示中固定条款：仅允许引用上下文 JSON/Cypher 结果中出现的字段与边；对图中不存在的命题一律回答「当前图谱未收录」或给出**可验证**的补数建议（例如「需导入含 X 的会话」），不得虚构该 Person 的经历或诊断。

**与现有代码的关系**：

- 导入阶段 `app/llm/persona_llm.py` 当前以**会话消息样本**为主做增强；第一层落地后，应增加（或切换为）**「子图 JSON → DeepSeek」**路径：先 `MATCH` 子图，再 `maybe_enrich_*` 变体，使线上「解释 Person」与离线「抽 trait」两条链路证据来源一致。  
- 对外 API 形态可与 **5.8 `POST /narrate`** 合并实现，或拆为 `POST /api/v1/person/{subject_id}/reason`（仅内部/受控 Key），由同一 **GraphContextPack** 构建器供二者复用。

**验收（第一层）**：

- 任意回答中声称的特质 / 关系类型 / 典型对话主题，能在子图或 `persona-export` 中找到对应节点或属性，或已被标注为「非图证据」。  
- 日志与审计：请求级记录 `subject_id`、所用 `batch_id`、裁剪统计，**不**把完整子图原文写入公共日志。

---

## 6. 抽取管道（Worker）

1. **解析**：按 `source_type`（wechat_export | plain_text | csv_turns）解析为 turn 列表。
2. **抽取**：LLM 输出符合 `extracted_bundle.schema_version` 的 JSON（见 YAML 中 `json_schema_hint`）。
3. **校验**：Pydantic 模型 + 本体规则（允许的关系端点、枚举闭集）。
4. **写入**：单事务 `MERGE` 人/代理人/交互；`CREATE` 假设与证据（或 `MERGE` 证据键）。
5. **后处理**：可选情绪/主题打标（独立属性，不冒充临床量表）。

---

## 7. 安全

- 鉴权：演示可用 API Key；生产 JWT + 租户 `tenant_id` 属性隔离。  
- 日志：**不记录**原始消息全文到应用日志；仅 `subject_id` + `job_id`。  
- Neo4j：仅内网；Bolt TLS。

---

## 8. 与 ONTOLOGY.yaml 的映射

- YAML 中每个 `classes.*.neo4j.labels` → 节点多标签策略。  
- `classes.*.properties` → 节点属性白名单；多余键写入前剥离或进 `_raw` 调试字段（默认关闭）。  
- `relationships.`* → Cypher 关系类型与端点类约束。

---

## 9. 验收清单

- 虚构数据一键导入，图内节点数 > 30。  
- 至少 2 个预置查询在 UI 可点。  
- 任一 `TraitHypothesis` 可从 UI 跳转到 `Evidence` → `Utterance`。  
- README：一键 `docker compose up` 起 Neo4j + API。

---

*版本：0.1 — 随 `ontology/ONTOLOGY.yaml` 演进。*