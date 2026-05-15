# 微信本地数据导出 → POG（wx-cli）

本流程基于开源工具 **[wx-cli](https://github.com/jackwener/wx-cli)**：在本机解密并读取**您自己**的微信数据，导出为 JSON 后由 POG 写入 Neo4j。  
**请务必在数据提供者知情同意的前提下使用**；工具原作者免责声明见 [wx-cli README](https://github.com/jackwener/wx-cli#免责声明)。

**两种方式**（二选一或组合）：

1. **前端向导（推荐）**：后端在 `WX_CLI_ENABLED=true` 时提供 `GET /api/v1/wechat/sessions` 列出会话，用户选择后 `POST /api/v1/wechat/import-from-session` 由后端子进程执行 `wx export … --format json` 并写入图库（勿将后端暴露在公网）。  
2. **手动粘贴**：本地运行 `wx export … --format json`，将完整 JSON 粘到 `POST /api/v1/ingest`（`source_type=wechat_export`）。

## 1. 安装 wx-cli

任选其一（详见上游文档）：

- **npm**：`npm install -g @jackwener/wx-cli`
- **Windows PowerShell（管理员）**：`irm https://raw.githubusercontent.com/jackwener/wx-cli/main/install.ps1 | iex`
- **Release 二进制**：[Releases](https://github.com/jackwener/wx-cli/releases)

## 2. 初始化（每台机器一次）

- **Windows**：管理员 PowerShell 执行 `wx init`，并保持 **微信（Weixin）已登录运行**。
- **macOS**：需按 wx-cli 文档对 WeChat.app 签名等步骤后再 `sudo wx init`。

验证：`wx sessions` 能列出会话即正常。

## 3. 导出为 JSON

与 [wx-cli `export.rs`](https://github.com/jackwener/wx-cli/blob/main/src/cli/export.rs) 一致，根对象包含：

- `chat`：会话名  
- `is_group`：是否群聊  
- `messages`：数组，每项含 `time`、`sender`、`content`（字符串）

示例（导出到文件）：

```bash
wx export "好友或群名称" --format json -o chat.json
```

或输出到 stdout 再重定向：

```bash
wx export "好友或群名称" -n 500 --format json > chat.json
```

## 4. 在 POG 中导入

### 4A. 前端选择会话（需环境变量）

在 `backend/.env` 中设置：

- `WX_CLI_ENABLED=true`
- `WX_CLI_COMMAND=wx`（若可执行文件不在 PATH，可写绝对路径）
- `WX_CLI_TIMEOUT_SEC=120`（按需）

重启 API 后：

1. 打开前端 **数据导入** → 来源选 **微信导出**。  
2. 点击 **加载会话列表**（调用 `wx sessions --json`）。  
3. 在表格中**单选**一个会话；系统会调用 `preview-export` 用较小 `-n` **预解析说话人**，在下拉框中选择 **本体化 Person** 与 **对话中的我**（`subject_id` 由所选说话人生成 `wxp_<hash>`，与 `sender` 自动对齐）。  
4. 可选调整 **导出条数**（正式 `wx export -n`，不超过单次上限）。  
5. 点击 **从 wx-cli 导出并导入**。  
6. 若改用手动粘贴 JSON：将正文粘贴后点 **解析正文 JSON 中的说话人**，同样在下拉框中选择；需要自定义主键时勾选 **手动填写**。

### 4B. 手动粘贴 JSON

1. **来源** 选择 **微信导出（wechat_export）**。  
2. **正文**：粘贴 `chat.json` 的**完整 JSON**。  
3. 点击 **解析正文 JSON 中的说话人**，在下拉框中选择 **本体化 Person** 与 **对话中的我**（或勾选「手动填写」）。  
4. 提交 `POST /api/v1/ingest`。

写入语义（当前实现）：`MERGE` `Person` 后创建一批特质节点（`PersonaSummary`、`ExpressionStyleTrait`、`VerbalTicObservation`、`MbtiHypothesisFacet`、`DialogueExemplar`、`PersonaAnalysisMeta`），经 `HAS_*` 关系挂到该 Person；同一 `subject_id` 再次导入会先按 `last_persona_batch_id` 删除旧批次特质子图。Person 上不再保留长 JSON 特质字段（已清空）。不含 `Agent` / `Utterance` 全量对话。

单次导入消息上限见后端常量（当前 8000 条）。

## 5. 常见问题

| 问题 | 处理 |
|------|------|
| 以前导入图里出现 `unknown` / `wx_cli_export` | 旧版把空 `sender` 落成 `unknown` Agent，并把渠道写成 `wx_cli_export` 的 `Interaction`；**当前版本不再创建这些节点**，只更新 `Person`。历史脏数据请用 `scripts/neo4j_wipe.py` 或 Cypher 自行清理。 |
| 422 校验失败 | 检查是否选了 wechat_export、正文是否为合法 JSON |
| 502 `找不到 … 消息记录` | 会话名与 `wx export` 所需不一致；单字母英文名已自动尝试大小写互换。仍失败请在终端执行 `wx export "会话名" --format json -n 5` 核对名称 |
| 503（wechat/sessions 等） | 未设置 `WX_CLI_ENABLED=true` 或后端无法调用本机 `wx` |
| Vite 代理 `ECONNREFUSED 127.0.0.1:8000` | 先在本机启动 API（`uvicorn … --port 8000`），再开前端 `npm run dev` |

## 6. 与「纯文本」导入的区别

| `source_type` | 行为 |
|----------------|------|
| `plain_text` / `other` | 占位：不落库 |
| `wechat_export` | 解析 wx-cli JSON 并 **写入 Neo4j** |

---

*POG 侧实现：`backend/app/ingest/wx_cli.py`、`POST /api/v1/ingest`；本机 wx-cli 封装：`backend/app/wechat_cli/runner.py`、`backend/app/api/wechat.py`。*
