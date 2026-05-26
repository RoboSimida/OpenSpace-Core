# OpenSpace-Core — AI Agent 自我进化引擎（最小实现）

> **这是 [OpenSpace](https://github.com/HKUDS/OpenSpace) 的最小核心实现。**
>
> 原项目包含云端 Skill 社区、Web 仪表盘、通信网关（WhatsApp/飞书）、基准测试套件等功能。
> 本版本仅保留核心的 **Skill 自我进化引擎 + MCP 服务**，去除了所有非必要的附加模块，
> 专注于让个人 Agent 能够从任务经验中自动学习、修复和改进 Skill。
>
> 如需完整功能（云端同步、社区共享、仪表盘、通信网关），请访问原始仓库：
> **[HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace)**

**让你的 AI Agent 从经验中学习、自动修复错误、持续进化 Skill。**

支持 Claude Code、Codex、OpenClaw、nanobot、Cursor 等任意 MCP Agent。

---

## 功能

OpenSpace 以 MCP Server 形式接入你的 Agent，提供：

### 🧬 Skill 自我进化

| 模式 | 说明 |
| ---- | ---- |
| **AUTO-FIX** | Skill 出错时自动修复损坏的指令 |
| **AUTO-IMPROVE** | 成功模式自动升级为更优版本 |
| **AUTO-LEARN** | 从实际使用中捕获高效工作流 |
| **质量监控** | 追踪 Skill 的应用率、成功率、回退率 |

### 🔧 MCP 工具

| 工具 | 说明 |
| ---- | ---- |
| `execute_task` | 代理执行任务，自动匹配 Skill 并在完成后分析进化 |
| `fix_skill` | 手动修复指定的损坏 Skill |

### 📊 能力

- **智能 Skill 匹配**：BM25 + embedding + LLM 三阶段检索，精准选择合适 Skill
- **版本谱系追踪**：每次进化记录完整 Diff，支持追溯
- **质量保障**：进化前自动确认、安全检查、反循环守卫
- **本地持久化**：SQLite 存储所有 Skill 记录与进化历史

---

## 快速开始

### 安装

```bash
git clone https://github.com/HKUDS/OpenSpace.git && cd OpenSpace
pip install -e .
openspace-mcp --help   # 验证安装
```

### 接入你的 Agent

在任何支持 MCP 的 Agent 配置中添加：

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "toolTimeout": 600,
      "env": {
        "OPENSPACE_HOST_SKILL_DIRS": "/path/to/your/agent/skills",
        "OPENSPACE_WORKSPACE": "/path/to/OpenSpace"
      }
    }
  }
}
```

将 Skill 复制到 Agent 的 skill 目录：

```bash
cp -r openspace/host_skills/delegate-task/ /path/to/your/agent/skills/
cp -r openspace/host_skills/skill-discovery/ /path/to/your/agent/skills/
```

完成。这两项 Skill 会教你的 Agent 何时及如何使用 OpenSpace。

### 直接使用（CLI）

```bash
# 交互模式
openspace

# 单任务模式
openspace --model "anthropic/claude-sonnet-4-5" --query "你的任务描述"
```

### 作为 MCP 服务运行

```bash
# stdio（默认）
openspace-mcp

# SSE 模式（HTTP）
openspace-mcp --transport sse --port 8080

# Streamable HTTP
openspace-mcp --transport streamable-http --port 8080
```

---

## 本地 Skill 同步

Skill 以目录 + `SKILL.md` 文件形式存储，可以像普通文件一样同步：

```bash
# 用 git 同步 skill 目录
git add openspace/skills/ && git commit -m "sync skills" && git push

# 或用 rsync / 网盘
rsync -av openspace/skills/ /backup/skills/
```

支持 `OPENSPACE_HOST_SKILL_DIRS` 环境变量指定多个 skill 目录，目录每次调用都会重新扫描。

---

## 环境变量

| 变量 | 说明 | 默认值 |
| ---- | ---- | ------ |
| `OPENSPACE_MODEL` | LLM 模型名 | 自动检测 |
| `OPENSPACE_HOST_SKILL_DIRS` | Agent Skill 目录（逗号分隔） | — |
| `OPENSPACE_WORKSPACE` | 工作目录 | — |
| `OPENSPACE_MAX_ITERATIONS` | 最大迭代次数 | 20 |
| `OPENSPACE_ENABLE_RECORDING` | 启用执行录制 | true |
| `OPENSPACE_MCP_HOST` | MCP HTTP 绑定地址 | 127.0.0.1 |
| `OPENSPACE_MCP_PORT` | MCP HTTP 端口 | 8080 |
| `OPENSPACE_MCP_TRANSPORT` | MCP 传输方式 | auto |

详细配置参见 [`openspace/config/README.md`](openspace/config/README.md)。

---

## 项目结构

``` text
openspace/
  __init__.py            # 包入口
  __main__.py            # CLI 入口
  mcp_server.py          # MCP 服务器（execute_task / fix_skill）
  tool_layer.py          # OpenSpace 主引擎
  skill_engine/          # 核心：Skill 注册、分析、进化、持久化
  grounding/             # 后端系统（Shell / MCP / Web / GUI）
  agents/                # 执行 Agent（工具调用、Skill 注入）
  llm/                   # LLM 客户端（litellm 封装）
  host_detection/        # 宿主 Agent 自动检测
  host_skills/           # 宿主注入 Skill（delegate-task / skill-discovery）
  platforms/             # 平台抽象（截图、系统信息）
  recording/             # 执行录制
  prompts/               # LLM 提示词模板
  config/                # 配置系统
  utils/                 # 工具类
  skills/                # 内置 Skill 目录
```

---

## Python API

```python
import asyncio
from openspace import OpenSpace

async def main():
    async with OpenSpace() as cs:
        result = await cs.execute("分析 GitHub trending 项目，生成报告")
        print(result["response"])

        for skill in result.get("evolved_skills", []):
            print(f"  进化: {skill['name']} ({skill['origin']})")

asyncio.run(main())
```

---

## 参考项目

OpenSpace 构建于以下开源项目之上：

- **[AnyTool](https://github.com/HKUDS/AnyTool)** — 通用工具层
- **[ClawWork](https://github.com/HKUDS/ClawWork)** — AI 协作者评测协议
- **[LiteLLM](https://github.com/BerriAI/litellm)** — 多模型统一接口
- **[MCP](https://modelcontextprotocol.io/)** — Model Context Protocol

该项目完整版原始仓库：[HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace)

---

<!-- markdownlint-disable MD033 MD036-->
<div align="center">

**🌟 如果 OpenSpace 对你有帮助，请给项目一颗 Star！**

**🧬 让 Agent 自我进化 · 💰 更少 Token · 🚀 更聪明**

</div>
<!-- markdownlint-enable MD033 MD036-->
