# POG — Personality Ontology Graph（人格本体图）

心理学 × 知识图谱 × 生成式 AI 方向的**可演进基层数据与推理层**原型：将聊天导出等文本经解析与（可选）LLM 增强后，写入 **Neo4j** 中可查询的 **Person** 与特质子图；前端提供导入、图浏览与结果导出。

> **边界**：人格相关输出均为**探索性假设**，非临床诊断、非标准化职业测评；处理真实数据须合规与脱敏。详见 `docs/ETHICS_AND_DATA.md`、`docs/PERSONA_INFERENCE_REFERENCES.md`。

---

## 技术栈

| 层级 | 选型 |
|------|------|
| 图数据库 | Neo4j 5.x（本地 Bolt 或 Neo4j Aura） |
| 后端 | Python 3.11+，FastAPI，Pydantic Settings，`neo4j` 驱动 |
| 前端 | Vue 3，Vite 8 |
| LLM（可选） | DeepSeek（OpenAI 兼容 API），用于人格摘要等增强；未配置时回退启发式 |
| 本机微信（可选） | `wx-cli` 子进程导出会话 JSON（需显式开启环境变量，勿对公网暴露） |

---

## 仓库结构

```
Ontology/
├── backend/                 # FastAPI 应用
│   ├── app/                 # main、api、ingest、llm、db
│   ├── scripts/             # 如 neo4j_wipe.py（清空图）
│   ├── ONTOLOGY.yaml        # 本体与字段级语义（与实现对齐时作真源）
│   ├── requirements.txt
│   └── .env.example         # 环境变量模板（复制为 .env）
├── front/                   # Vue + Vite 前端
│   └── src/views/           # 导入、图浏览、API 文档页等
├── docs/                    # 项目文档（简报、规格、运维等）
├── chat.json                # 可选：开发时根目录聊天 JSON 样例（勿提交敏感内容）
└── README.md                # 本文件
```

---

## 快速开始

**完整步骤（conda 环境、Neo4j 校验、清空库、前后端命令）见：[`docs/OPERATIONS.md`](docs/OPERATIONS.md)。**

极简摘要：

1. **Neo4j**：准备实例；在 `backend/.env` 中配置 `NEO4J_URI`、`NEO4J_USER` / `NEO4J_USERNAME`、`NEO4J_PASSWORD`、`NEO4J_DATABASE`（见 `.env.example`）。  
2. **后端**（推荐 conda）：`cd backend` → `conda create -n pog python=3.11 -y` → `conda activate pog` → `pip install -r requirements.txt` → `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`。  
3. **健康检查**：打开 `http://127.0.0.1:8000/health/neo4j` 确认图库可读。  
4. **前端**：`cd front` → `npm install` → `npm run dev`（默认将 `/api` 代理到本机 `8000` 端口）。

OpenAPI：`http://127.0.0.1:8000/docs`。

---

## 当前已实现能力（MVP）

- **微信 / 聊天 JSON 导入**：`POST /api/v1/ingest`、`POST /api/v1/ingest/chat-json`；可选本机 `wx-cli` 会话导出（`docs/WECHAT_WX_CLI.md`）。  
- **人格特质子图写入 Neo4j**：摘要、表达风格、口癖、情绪维度、社会关系草图、大五/MBTI/九型占位或 LLM 假设、典型对话片段、分析元数据、**显著特质**（`SalientTraitObservation`）等。  
- **Person 子图与可视化**：`GET /api/v1/persons`、`GET /api/v1/person/{subject_id}/subgraph`（前端「图数据」页按 Person 查阅）；`GET /api/v1/graph/nodes` 全库节点分页（调试）。  
- **结果导出**：`GET /api/v1/person/{subject_id}/persona-export?format=json|text`（开放接口页按 Person 下载）。  
- **清空开发库**：在已激活的 conda 环境（或 venv）下于 `backend` 目录执行 `python scripts/neo4j_wipe.py --dry-run` / `--yes`（详见运维文档）。

## 文档索引

| 文档 | 说明 |
|------|------|
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | **操作指引**：前后端启动、Neo4j 连接确认、清空库 |
| [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) | 项目简报、定位与创新点 |
| [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md) | API 与架构规格、约束与验收方向 |
| [`docs/WECHAT_WX_CLI.md`](docs/WECHAT_WX_CLI.md) | 本机 wx-cli 集成与安全注意 |
| [`docs/PERSONA_INFERENCE_REFERENCES.md`](docs/PERSONA_INFERENCE_REFERENCES.md) | 文本人格推断文献与使用边界 |
| [`docs/ETHICS_AND_DATA.md`](docs/ETHICS_AND_DATA.md) | 伦理与数据处理原则 |
| [`docs/PRESENTATION_SHOWCASE.md`](docs/PRESENTATION_SHOWCASE.md) | **展演文档**：内容、目的、演示流程、未来方向、伦理与 Q&A |
| [`docs/PITCH_ONE_PAGER.md`](docs/PITCH_ONE_PAGER.md) | 一页纸答辩结构 |
| [`docs/BRAND_AND_TRADEMARK.md`](docs/BRAND_AND_TRADEMARK.md) | **商业 IP / 品牌与商标**（命名、尼斯分类、VI、图形标 `docs/brand/pog-mark.svg`） |

本体定义（演进中）：[`backend/ONTOLOGY.yaml`](backend/ONTOLOGY.yaml)。

---

## 参与贡献与版本

文档版本以各 `docs/*.md` 内说明为准；图模式版本见 Neo4j 中 `facet_schema_version` / 应用常量（如 `wx_persona_graph_v4`）。

欢迎通过 Issue / PR 改进文档与实现；提交前请勿将 `.env`、真实聊天内容或密钥纳入版本库。
