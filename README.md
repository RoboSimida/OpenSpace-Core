# OpenSpace-Core — Self-Evolving Skill Engine for AI Agents (Minimal Core)

> **This is a minimal core implementation of [OpenSpace](https://github.com/HKUDS/OpenSpace).**
>
> The original project includes a cloud skill community, web dashboard, communication gateway
> (WhatsApp/Feishu), benchmark suite, and more. This version keeps only the essential
> **skill self-evolution engine + MCP server**, removing all non-essential modules to focus
> on letting your personal agent learn, fix, and improve skills from task experience.
>
> For the full feature set (cloud sync, community sharing, dashboard, communication gateway),
> see the original repository: **[HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace)**

**One command to evolve your AI Agent.** Works with Claude Code, Codex, OpenClaw, nanobot, Cursor, and any MCP agent.

---

## Features

OpenSpace connects to your agent as an MCP server, providing:

### 🧬 Skill Self-Evolution

| Mode | Description |
| ---- | ----------- |
| **AUTO-FIX** | Repairs broken skill instructions on failure |
| **AUTO-IMPROVE** | Upgrades successful patterns into better versions |
| **AUTO-LEARN** | Captures winning workflows from actual usage |
| **Quality Monitoring** | Tracks applied rate, completion rate, fallback rate |

### 🔧 MCP Tools

| Tool | Description |
| ---- | ----------- |
| `execute_task` | Delegates a task, auto-matches skills, analyzes and evolves after completion |
| `fix_skill` | Manually fix a broken skill with a specific direction |

### 📊 Capabilities

- **Smart Skill Matching**: BM25 + embedding + LLM three-stage retrieval for precise skill selection
- **Version Lineage Tracking**: Full diff records for every evolution, complete ancestry graph
- **Safety Guards**: Pre-evolution confirmation, anti-loop protection, security checks
- **Local Persistence**: SQLite storage for all skill records and evolution history

---

## Quick Start

### Install

```bash
git clone https://github.com/HKUDS/OpenSpace.git && cd OpenSpace
pip install -e .
openspace-mcp --help   # verify installation
```

### Connect to Your Agent

Add to any MCP-compatible agent's config:

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

Copy the host skills into your agent's skill directory:

```bash
cp -r openspace/host_skills/delegate-task/ /path/to/your/agent/skills/
cp -r openspace/host_skills/skill-discovery/ /path/to/your/agent/skills/
```

Done. These two skills teach your agent when and how to use OpenSpace.

### CLI Usage

```bash
# Interactive mode
openspace

# Single task mode
openspace --model "anthropic/claude-sonnet-4-5" --query "Create a monitoring dashboard for my Docker containers"
```

### Run as MCP Service

```bash
# stdio (default)
openspace-mcp

# SSE mode (HTTP)
openspace-mcp --transport sse --port 8080

# Streamable HTTP
openspace-mcp --transport streamable-http --port 8080
```

---

## Local Skill Sync

Skills are directories with `SKILL.md` files — sync them like any other files:

```bash
# Via git
git add openspace/skills/ && git commit -m "sync skills" && git push

# Via rsync or cloud drive
rsync -av openspace/skills/ /backup/skills/
```

Use `OPENSPACE_HOST_SKILL_DIRS` to specify multiple skill directories, re-scanned on every call.

---

## Environment Variables

| Variable | Description | Default |
| ---- | ----------- | ------- |
| `OPENSPACE_MODEL` | LLM model name | Auto-detect |
| `OPENSPACE_HOST_SKILL_DIRS` | Agent skill dirs (comma-separated) | — |
| `OPENSPACE_WORKSPACE` | Working directory | — |
| `OPENSPACE_MAX_ITERATIONS` | Max iterations per task | 20 |
| `OPENSPACE_ENABLE_RECORDING` | Enable execution recording | true |
| `OPENSPACE_MCP_HOST` | MCP HTTP bind address | 127.0.0.1 |
| `OPENSPACE_MCP_PORT` | MCP HTTP port | 8080 |
| `OPENSPACE_MCP_TRANSPORT` | MCP transport mode | auto |

See [`openspace/config/README.md`](openspace/config/README.md) for advanced configuration.

---

## Project Structure

``` text
openspace/
  __init__.py            # Package entry
  __main__.py            # CLI entry
  mcp_server.py          # MCP server (execute_task / fix_skill)
  tool_layer.py          # OpenSpace main engine
  skill_engine/          # Core: skill registration, analysis, evolution, persistence
  grounding/             # Backend system (Shell / MCP / Web / GUI)
  agents/                # Execution agent (tool calling, skill injection)
  llm/                   # LLM client (litellm wrapper)
  host_detection/        # Auto-detect host agent credentials
  host_skills/           # Host-injected skills (delegate-task / skill-discovery)
  platforms/             # Platform abstraction (screenshots, system info)
  recording/             # Execution recording
  prompts/               # LLM prompt templates
  config/                # Configuration system
  utils/                 # Utilities
  skills/                # Built-in skill directory
```

---

## Python API

```python
import asyncio
from openspace import OpenSpace

async def main():
    async with OpenSpace() as cs:
        result = await cs.execute("Analyze GitHub trending repos and create a report")
        print(result["response"])

        for skill in result.get("evolved_skills", []):
            print(f"  Evolved: {skill['name']} ({skill['origin']})")

asyncio.run(main())
```

---

## Related Projects

OpenSpace builds upon these open-source projects:

- **[AnyTool](https://github.com/HKUDS/AnyTool)** — Universal tool-use layer for AI agents
- **[ClawWork](https://github.com/HKUDS/ClawWork)** — AI coworker evaluation protocol
- **[LiteLLM](https://github.com/BerriAI/litellm)** — Multi-model unified interface
- **[MCP](https://modelcontextprotocol.io/)** — Model Context Protocol

Original full-featured repository: **[HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace)**

---

<!-- markdownlint-disable MD033 MD036-->
<div align="center">

## ⭐ Star History

If you find OpenSpace helpful, please consider giving us a star!

**🧬 Make Your Agent Self-Evolve · 💰 Fewer Tokens · 🚀 Smarter Agents**

</div>
<!-- markdownlint-enable MD033 MD036-->
