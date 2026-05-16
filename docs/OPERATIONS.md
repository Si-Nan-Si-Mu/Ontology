# POG 操作指引（前后端启动、Neo4j、清空库）

面向本地开发与联调：启动顺序建议 **Neo4j（或 Aura）可用 → 后端 → 前端**。不要将带真实密钥的 `.env` 提交到版本库。

## 1. 环境准备


| 组件      | 说明                                                                         |
| ------- | -------------------------------------------------------------------------- |
| Python  | 建议 3.11+（与 `backend/requirements.txt` 中依赖兼容）                               |
| Conda   | **推荐**：用独立环境管理后端依赖（示例环境名 `pog`）；避免 Windows 上 `.venv` 路径与 `Activate.ps1` 混淆 |
| Node.js | `front/package.json` 要求 **^20.19.0 或 ≥22.12.0**                            |
| Neo4j   | 本地 Docker/桌面版 **bolt://127.0.0.1:7687**，或 **Neo4j Aura**（`neo4j+s://…`）    |


在仓库根目录外无需额外全局工具；依赖分别在 `backend` 与 `front` 目录安装。

## 2. 后端（FastAPI）

### 2.1 安装依赖（推荐：conda）

```powershell
cd D:\Python\Ontology\backend
conda create -n pog python=3.11 -y
conda activate pog
pip install -r requirements.txt
```

- 环境名 `pog` 仅为示例；若已占用可改为 `pog-ontology` 等。  
- **Linux / macOS**：同样使用 `conda create` / `conda activate`（需已安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 或 Anaconda）。

**备选：`python -m venv`（本仓库不自带 `.venv` 目录）**

- Windows **PowerShell**：`python -m venv .venv` 后执行 `.\.venv\Scripts\Activate.ps1`（若策略限制，可对当前用户放宽执行策略后再试）。  
- Windows **cmd**：`.\.venv\Scripts\activate.bat`  
- Linux / macOS：`source .venv/bin/activate`

### 2.2 配置环境变量

1. 复制示例文件（PowerShell：`Copy-Item .env.example .env`；cmd：`copy .env.example .env`）。
2. 编辑 `backend/.env`，至少配置 **Neo4j**（见下节）。
3. 变量名与含义与 `app/config.py` 一致：
  - `NEO4J_URI`：如 `bolt://127.0.0.1:7687` 或 Aura 的 `neo4j+s://…`  
  - `NEO4J_USER` 或 `NEO4J_USERNAME`：用户名  
  - `NEO4J_PASSWORD`：密码  
  - `NEO4J_DATABASE`：可选；本地社区版常留空；Aura 控制台可能给出具体库名

可选：微信 wx-cli、DeepSeek 等见 `.env.example` 注释；不影响「仅验证图库连接」。

### 2.3 启动 API

```powershell
cd D:\Python\Ontology\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 应用启动时会调用 `**Neo4jConnection.verify_connectivity()**`；若 URI/账号/网络错误，进程会**启动失败**，请先修正 `.env`。  
- 默认 CORS 允许本机 Vite：`http://127.0.0.1:5173`、`http://localhost:5173` 等（见 `app/main.py`）。

### 2.4 常用 URL


| 路径                                                                       | 说明                                              |
| ------------------------------------------------------------------------ | ----------------------------------------------- |
| [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)                 | Swagger UI                                      |
| [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)             | 进程存活                                            |
| [http://127.0.0.1:8000/health/neo4j](http://127.0.0.1:8000/health/neo4j) | **确认 Neo4j 可执行只读查询**（返回 `ok: true` 与服务器时间则连接正常） |


命令行快速检查（需已启动后端）：

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/neo4j
```

## 3. Neo4j 连接确认

1. **后端能启动**：说明驱动层 `verify_connectivity` 已通过。
2. **接口确认**：浏览器或 `curl` 打开 `GET /health/neo4j`，`ok` 为 `true` 即当前配置下的库可读。
3. **Aura**：在控制台核对实例状态、IP 允许名单、库名与 URI 是否与 `.env` 一致。
4. **本地 Neo4j**：确认服务已监听 `7687`，防火墙未拦截；首次安装需改默认密码后再写入 `.env`。

若仅做「空库联调」，可先执行下文「清空库」再导入数据。

## 4. 前端（Vite + Vue）

### 4.1 安装与启动

```powershell
cd D:\Python\Ontology\front
npm install
npm run dev
```

默认开发服务器一般为 **[http://127.0.0.1:5173](http://127.0.0.1:5173)**（以终端输出为准）。

### 4.2 与后端的对接方式

- **开发默认**：`vite.config.js` 已将 `/api`、`/health`、`/docs`、`/openapi.json`、`/redoc` **代理到** `http://127.0.0.1:8000`，前端可不配环境变量即可调用同源路径。  
- **直连后端（如手机/另一台机访问前端）**：在 `front` 下设置环境变量 `**VITE_API_ORIGIN`**（例如 `http://127.0.0.1:8000`），再 `npm run dev`，详见 `front/src/api/http.js` 注释。

### 4.3 生产构建（可选）

```powershell
cd D:\Python\Ontology\front
npm run build
npm run preview
```

部署时需自行配置反向代理或 `VITE_API_ORIGIN`，使浏览器能访问真实 API 源。

## 5. 清空 Neo4j 图数据

**危险操作**：会删除当前连接库中的**全部节点与关系**（`MATCH (n) DETACH DELETE n`）。仅用于开发/演示库；生产或共享实例务必再三确认。

### 5.1 推荐：项目脚本（需显式 `--yes`）

在 `**backend` 目录**执行（以便加载同目录下的 `.env`）：

```powershell
cd D:\Python\Ontology\backend

# 仅统计节点数，不写库
python scripts/neo4j_wipe.py --dry-run

# 确认无误后执行清空
python scripts/neo4j_wipe.py --yes
```

脚本会先 `verify_connectivity`，再统计、删除；逻辑见 `backend/scripts/neo4j_wipe.py`。

### 5.2 手动（Neo4j Browser / cypher-shell）

在**当前要清空的数据库**中执行：

```cypher
MATCH (n) DETACH DELETE n
```

Aura 请在控制台选对 **Database**，避免误删其他环境。

## 6. 建议的联调顺序（简表）

1. 配置 `backend/.env` 中 Neo4j。
2. `uvicorn` 启动后端 → 访问 `/health/neo4j`。
3. （可选）`python scripts/neo4j_wipe.py --dry-run` / `--yes` 清空。
4. `npm run dev` 启动前端 → 在导入页或图浏览页验证写入与查询。

## 7. 相关文档

- 技术栈与接口概览：`docs/TECH_SPEC.md`  
- 微信 wx-cli 与安全：`docs/WECHAT_WX_CLI.md`  
- 人格推断边界与文献：`docs/PERSONA_INFERENCE_REFERENCES.md`  
- 环境变量模板：`backend/.env.example`

