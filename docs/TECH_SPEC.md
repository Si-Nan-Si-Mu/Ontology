# POG 技术规格书（v0.1）

本文与 `ontology/ONTOLOGY.yaml` 同步；实现以 YAML 为**语义真源**，Neo4j 为**运行库**。

---

## 1. 技术栈

| 层 | 选型（默认） |
|----|----------------|
| 图库 | Neo4j 5.x（Community 可满足演示；生产考虑 Enterprise 与 RBAC） |
| 后端 | Python 3.11+，FastAPI，Pydantic v2 |
| 驱动 | `neo4j` 官方驱动（异步可选） |
| 任务队列 | RQ 或 Celery（长耗时抽取） |
| 前端 | Vue 3 + TypeScript，Vite；图可视化 neovis.js / @antv/g6（二选一） |
| LLM | 可插拔（OpenAI 兼容 API / 本地）；抽取输出 **JSON Schema 强约束** |

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

| 概念 | 规则 |
|------|------|
| `subject_id` | 系统内 UUID；对外业务 ID 可映射 |
| `Person` 节点 | `subject_id` **唯一约束** |
| `Interaction` | `interaction_key = hash(person_id, channel, start_ts, normalized_summary)` 可选唯一 |
| `Utterance` | `utterance_key` 由 `(interaction_id, sequence)` 或内容哈希决定 |
| `Evidence` | `evidence_key` 由 `(extractor_version, anchor_ref)` 哈希，避免重复写入 |

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
- **`self_speaker_label`**：当 `source_type=wechat_export` 时**必填**，须与 wx-cli 导出 JSON 中每条消息的 `sender` 一致。
- **`raw_text`**：`plain_text` 时可空；`wechat_export` 时为 **wx-cli `wx export … --format json` 的完整 JSON 字符串**（根对象含 `messages`、`chat`、`is_group`）。
- **`source_type`**：`plain_text` | `wechat_export` | `other`（`plain_text` / `other` 当前为占位不落库；`wechat_export` 写入 Neo4j）。

**Response**：`plain_text` 等为占位 JSON；`wechat_export` 成功时含 `wx_cli.mode`（`persona_facet_graph`）、`facet_nodes_created`、`persona_batch_id` 等。

缺少或空白 `subject_id`，或 `wechat_export` 缺少正文 / `self_speaker_label` 时返回 **422**。JSON 非法或结构不符时返回 **400**。

`multipart` 文件上传为后续迭代。

### 5.1.1 本机 wx-cli（可选，`WX_CLI_ENABLED=true`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/wechat/status` | 是否启用、`wx` 是否在 PATH 等 |
| GET | `/api/v1/wechat/sessions` | 子进程 `wx sessions --json`，供前端选择会话 |
| POST | `/api/v1/wechat/preview-export` | Body：`chat`、`probe_limit`；返回说话人频次与 `suggested_subject_id` |
| POST | `/api/v1/wechat/analyze-json` | Body：`raw_text`；同上，不调用本机 `wx` |
| POST | `/api/v1/wechat/import-from-session` | Body：`subject_id`、`self_speaker_label`、`chat`（与导出所用会话名一致）、`limit` 等；内部 `wx export` → 与 `wechat_export` 相同写入逻辑 |

未启用时 `sessions` / `preview-export` / `import-from-session` 返回 **503**；`analyze-json` 不依赖 wx-cli，始终可用。仅建议在受信本机或内网部署使用。

### 5.2 `GET /jobs/{job_id}`

**Response**：`{ "status": "running|done|failed", "error": null, "stats": { "nodes_created": N } }`

### 5.3 `GET /persons`

列表分页：`?cursor=&limit=`

### 5.4 `GET /persons/{subject_id}/subgraph`

**Query**：`?focus=trait|agent|interaction&depth=2&limit_nodes=200`

**Response**：Neo4j 子图 JSON（nodes + relationships），供前端渲染；**禁止**返回全库。

### 5.5 `POST /graph/query`（内部或受控）

仅允许**预置查询模板 ID** + 绑定参数，防止 Cypher 注入；黑客松后可改为 GraphQL/Data API。

**预置查询示例 ID**：

| `query_id` | 说明 |
|--------------|------|
| `conflict_chain` | 某 `Person` 与指定 `Agent` 的高负面情绪交互路径 |
| `trait_evidence` | 某 `TraitHypothesis` 及 `SUPPORTED_BY` 证据树 |
| `timeline` | 时间排序的 `Interaction` 列表 |

### 5.6 `POST /narrate`（P1）

**Body**：`{ "subject_id", "locale", "max_evidence": 10 }`  
**流程**：子图检索 → 证据裁剪 → LLM 生成带 `[evidence_id]` 引用的 Markdown。

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
- `relationships.*` → Cypher 关系类型与端点类约束。

---

## 9. 验收清单（黑客松）

- [ ] 虚构数据一键导入，图内节点数 > 30。  
- [ ] 至少 2 个预置查询在 UI 可点。  
- [ ] 任一 `TraitHypothesis` 可从 UI 跳转到 `Evidence` → `Utterance`。  
- [ ] README：一键 `docker compose up` 起 Neo4j + API。

---

*版本：0.1 — 随 `ontology/ONTOLOGY.yaml` 演进。*
