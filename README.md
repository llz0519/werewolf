# 🐺 AI 狼人杀游戏 (LLM Werewolf Multi-Agent)

基于大模型（LLM）驱动的多智能体（Multi-Agent）狼人杀游戏。在这个游戏中，你可以作为真人玩家与一群性格各异的 AI 玩家斗智斗勇，或者纯粹开启“上帝视角”，观看 AI 们一本正经地相互欺骗、推理和“胡说八道”。

## ✨ 特色功能

- 🧠 **AI 智能体**：基于大模型（如 DeepSeek, Qwen）进行逻辑推理，支持完整的“思考（Thought）”与“伪装”过程链。
- 🎭 **经典角色板子**：支持【村民】、【狼人】、【预言家】、【女巫】和【猎人】。
- 🌚 **完整夜间交互**：狼人队内私语和投票击杀；预言家跨夜记忆与验人；女巫双药控制与逻辑。
- 🤖 **自动化法官**：全自动的阶段流转、白天黑夜切换、视角控制（夜晚视野脱敏），游戏进程完全自动推进。
- 💻 **可视化前端 UI**：React + Tailwind 构建的对局房间，可实时观察其他玩家的发言、票型以及上帝视角下的 AI “内心戏”。

## 🛠️ 技术栈

- **后端**: FastAPI, Pydantic, Python 3
- **前端**: React, Vite, TypeScript, Tailwind CSS
- **AI 驱动**: OpenAI 兼容 API（DeepSeek / Qwen 等大模型驱动）

## 🚀 快速开始

### 1. 环境准备与后端启动

1. 在根目录下复制 `.env.example`，创建并配置你的 `.env` 文件（需要填入你的大模型 API KEY）。
   ```ini
   LLM_API_KEY="sk-你的APIKEY"
   LLM_BASE_URL="对应的大模型API地址"
   ```
2. 创建并激活 Python 虚拟环境（推荐）：
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```
3. 启动 FastAPI 后端服务（游戏引擎与API）：
   ```bash
   uvicorn main:app --reload --host 0.0.0.1 --port 8000
   ```

### 2. 前端界面启动

1. 进入前端目录（通过根目录直接运行）：
   ```bash
   npm install
   npm run dev
   ```
2. 在浏览器中打开提示的本地地址（如 `http://localhost:5173`），即可进入游戏大厅。

### 3. 如何开局？

- **进入大厅**：在前端页面点击“创建本地单机对局”。系统将自动创建房间、自动加入 AI 角色并在后台静默拉起 `agent.py` 进程进行对局轮询。
- **纯看戏 / 亲自下场参战**：创建对局时可以选择是以“上帝视角（纯观战）”还是作为“玩家1（真人）”亲自下场。

## ⚠️ 注意事项

- **切勿泄露环境变量**：本项目的 `.gitignore` 已配置为忽略 `.env` 和 `.venv/`。请确保你在向 GitHub 推送时**不会**把包含自己私人 API KEY 的 `.env` 文件给推上去。
- **API 请求说明**：游戏有一定并发频次，使用时请确保你所配置的 LLM API 能承受多 Agent 同时调用的并发要求（如果速率受限，可以在 `ai_manager.py` 下调整相关参数或休眠时间）。
