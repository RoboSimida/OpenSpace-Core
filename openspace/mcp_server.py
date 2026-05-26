"""OpenSpace MCP Server

Exposes the following tools to MCP clients:
  execute_task   — Delegate a task (auto-registers skills, auto-searches, auto-evolves)
  fix_skill      — Manually fix a broken skill (FIX only; DERIVED/CAPTURED via execute_task)

Usage:
    python -m openspace.mcp_server                     # auto (TTY -> SSE, MCP host -> stdio)
    python -m openspace.mcp_server --transport sse     # SSE on port 8080
    python -m openspace.mcp_server --transport streamable-http  # Streamable HTTP on port 8080
    python -m openspace.mcp_server --port 9090         # SSE on custom port

Environment variables: see ``openspace/host_detection/``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class _MCPSafeStdout:
    """Stdout wrapper: binary (.buffer) → real stdout, text (.write) → stderr."""

    def __init__(self, real_stdout, stderr):
        self._real = real_stdout
        self._stderr = stderr

    @property
    def buffer(self):
        return self._real.buffer

    def fileno(self):
        return self._real.fileno()

    def write(self, s):
        return self._stderr.write(s)

    def writelines(self, lines):
        return self._stderr.writelines(lines)

    def flush(self):
        self._stderr.flush()
        self._real.flush()

    def isatty(self):
        return self._stderr.isatty()

    @property
    def encoding(self):
        return self._stderr.encoding

    @property
    def errors(self):
        return self._stderr.errors

    @property
    def closed(self):
        return self._stderr.closed

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    def __getattr__(self, name):
        return getattr(self._stderr, name)

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_real_stdout = sys.stdout

# Windows pipe buffers are small. When using stdio MCP transport,
# the parent process only reads stdout for MCP messages and does NOT
# drain stderr. Heavy log/print output during execute_task fills the stderr
# pipe buffer, blocking this process on write() → deadlock → timeout.
# Redirect stderr to a log file on Windows to prevent this.
if os.name == "nt":
    _stderr_file = open(
        _LOG_DIR / "mcp_stderr.log", "a", encoding="utf-8", buffering=1
    )
    sys.stderr = _stderr_file

sys.stdout = _MCPSafeStdout(_real_stdout, sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "mcp_server.log")],
)
logger = logging.getLogger("openspace.mcp_server")

from mcp.server.fastmcp import FastMCP

_fastmcp_kwargs: dict = {}
try:
    if "description" in inspect.signature(FastMCP.__init__).parameters:
        _fastmcp_kwargs["description"] = (
            "OpenSpace: Unite the Agents. Evolve the Mind. Rebuild the World."
        )
except (TypeError, ValueError):
    pass

mcp = FastMCP("OpenSpace", **_fastmcp_kwargs)

_openspace_instance = None
_openspace_lock = asyncio.Lock()
_standalone_store = None

# Internal state: tracks bot skill directories already registered this session.
_registered_skill_dirs: set = set()



async def _get_openspace():
    """Lazy-initialise the OpenSpace engine."""
    global _openspace_instance
    if _openspace_instance is not None and _openspace_instance.is_initialized():
        return _openspace_instance

    async with _openspace_lock:
        if _openspace_instance is not None and _openspace_instance.is_initialized():
            return _openspace_instance

        logger.info("Initializing OpenSpace engine ...")
        from openspace.tool_layer import OpenSpace, OpenSpaceConfig
        from openspace.host_detection import (
            build_grounding_config_path,
            build_llm_kwargs,
            load_runtime_env,
        )

        load_runtime_env()

        env_model = os.environ.get("OPENSPACE_MODEL", "")
        workspace = os.environ.get("OPENSPACE_WORKSPACE")
        max_iter = int(os.environ.get("OPENSPACE_MAX_ITERATIONS", "20"))
        enable_rec = os.environ.get("OPENSPACE_ENABLE_RECORDING", "true").lower() in ("true", "1", "yes")

        backend_scope_raw = os.environ.get("OPENSPACE_BACKEND_SCOPE")
        backend_scope = (
            [b.strip() for b in backend_scope_raw.split(",") if b.strip()]
            if backend_scope_raw else None
        )

        config_path = build_grounding_config_path()
        model, llm_kwargs = build_llm_kwargs(env_model)

        _pkg_root = str(Path(__file__).resolve().parent.parent)
        recording_base = workspace or _pkg_root
        recording_log_dir = str(Path(recording_base) / "logs" / "recordings")

        config = OpenSpaceConfig(
            llm_model=model,
            llm_kwargs=llm_kwargs,
            workspace_dir=workspace,
            grounding_max_iterations=max_iter,
            enable_recording=enable_rec,
            recording_backends=["shell"] if enable_rec else None, # ["shell", "mcp", "web"] if enable_rec else None
            recording_log_dir=recording_log_dir,
            backend_scope=backend_scope,
            grounding_config_path=config_path,
        )

        _openspace_instance = OpenSpace(config=config)
        await _openspace_instance.initialize()
        logger.info("OpenSpace engine ready (model=%s).", model)

        # Auto-register host bot skill directories from env (set once by human)
        host_skill_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
        if host_skill_dirs_raw:
            dirs = [d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()]
            if dirs:
                await _auto_register_skill_dirs(dirs)
                logger.info("Auto-registered host skill dirs from OPENSPACE_HOST_SKILL_DIRS: %s", dirs)

        return _openspace_instance


def _get_store():
    """Get SkillStore — reuses OpenSpace's internal instance when available."""
    global _standalone_store
    if _openspace_instance and _openspace_instance.is_initialized():
        internal = getattr(_openspace_instance, "_skill_store", None)
        if internal and not internal._closed:
            return internal
    if _standalone_store is None or _standalone_store._closed:
        from openspace.skill_engine import SkillStore
        _standalone_store = SkillStore()
    return _standalone_store


def _get_local_skill_registry():
    """Build a lightweight SkillRegistry for local-only skill search.

    This avoids initializing the full OpenSpace engine when callers only
    want to inspect local skills. It mirrors the skill directory discovery
    order used by the full engine, but skips LLM / provider startup.
    The registry is rebuilt per call so later local searches can see
    newly added skills without requiring a process restart.
    """
    from openspace.config import get_config
    from openspace.skill_engine import SkillRegistry

    skill_paths: List[Path] = []

    host_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
    if host_dirs_raw:
        for d in host_dirs_raw.split(","):
            d = d.strip()
            if not d:
                continue
            p = Path(d)
            if p.exists():
                skill_paths.append(p)
            else:
                logger.warning("Host skill dir does not exist: %s", d)

    try:
        skill_cfg = get_config().skills
    except Exception as e:
        logger.warning("Failed to load local skill config: %s", e)
        skill_cfg = None

    if skill_cfg and skill_cfg.skill_dirs:
        for d in skill_cfg.skill_dirs:
            p = Path(d)
            if p in skill_paths:
                continue
            if p.exists():
                skill_paths.append(p)
            else:
                logger.warning("Configured skill dir does not exist: %s", d)

    builtin_skills = Path(__file__).resolve().parent / "skills"
    if builtin_skills.exists():
        skill_paths.append(builtin_skills)

    if not skill_paths:
        logger.debug("No local skill directories found")
        return None

    registry = SkillRegistry(skill_dirs=skill_paths)
    registry.discover()
    return registry




async def _auto_register_skill_dirs(skill_dirs: List[str]) -> int:
    """Register bot skill directories into OpenSpace's SkillRegistry + DB.

    Called automatically by ``execute_task`` on every invocation. Directories
    are re-scanned each time so that skills created by the host bot since the last call are discovered immediately.
    """
    global _registered_skill_dirs

    valid_dirs = [Path(d) for d in skill_dirs if Path(d).is_dir()]
    if not valid_dirs:
        return 0

    openspace = await _get_openspace()
    registry = openspace._skill_registry
    if not registry:
        logger.warning("_auto_register_skill_dirs: SkillRegistry not initialized")
        return 0

    added = registry.discover_from_dirs(valid_dirs)

    db_created = 0
    if added:
        store = _get_store()
        db_created = await store.sync_from_registry(added)

    is_first = any(d not in _registered_skill_dirs for d in skill_dirs)
    for d in skill_dirs:
        _registered_skill_dirs.add(d)

    if added:
        action = "Auto-registered" if is_first else "Re-scanned & found"
        logger.info(
            f"{action} {len(added)} skill(s) from {len(valid_dirs)} dir(s), "
            f"{db_created} new DB record(s)"
        )
    return len(added)




def _format_task_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Format an OpenSpace execution result for MCP transport."""
    tool_execs = result.get("tool_executions", [])
    tool_summary = [
        {
            "tool": te.get("tool_name", te.get("tool", "")),
            "status": te.get("status", ""),
            "error": te.get("error", "")[:200] if te.get("error") else None,
        }
        for te in tool_execs[:20]
    ]

    output: Dict[str, Any] = {
        "status": result.get("status", "unknown"),
        "response": result.get("response", ""),
        "execution_time": round(result.get("execution_time", 0), 2),
        "iterations": result.get("iterations", 0),
        "skills_used": result.get("skills_used", []),
        "task_id": result.get("task_id", ""),
        "tool_call_count": len(tool_execs),
        "tool_summary": tool_summary,
    }
    if result.get("warning"):
        output["warning"] = result["warning"]

    # Format evolved_skills
    raw_evolved = result.get("evolved_skills", [])
    if raw_evolved:
        formatted_evolved = []
        for es in raw_evolved:
            skill_path = es.get("path", "")
            skill_dir = str(Path(skill_path).parent) if skill_path else ""
            formatted_evolved.append({
                "skill_dir": skill_dir,
                "name": es.get("name", ""),
                "origin": es.get("origin", ""),
                "change_summary": es.get("change_summary", ""),
            })
        output["evolved_skills"] = formatted_evolved

    return output


def _json_ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _json_error(error: Any, **extra) -> str:
    return json.dumps({"error": str(error), **extra}, ensure_ascii=False)


# MCP Tools (2 tools)
@mcp.tool()
async def execute_task(
    task: str,
    workspace_dir: str | None = None,
    max_iterations: int | None = None,
    skill_dirs: list[str] | None = None,
) -> str:
    """Execute a task with OpenSpace's full grounding engine.

    OpenSpace will:
    1. Auto-register bot skills from skill_dirs (if provided)
    2. Search for relevant skills from local registry
    3. Attempt skill-guided execution -> fallback to pure tools
    4. Auto-analyze -> auto-evolve (FIX/DERIVED/CAPTURED) if needed

    Note: This call blocks until the task completes (may take minutes).
    Set MCP client tool-call timeout >= 600 seconds.

    Args:
        task: The task instruction (natural language).
        workspace_dir: Working directory. Defaults to OPENSPACE_WORKSPACE env.
        max_iterations: Max agent iterations (default: 20).
        skill_dirs: Bot's skill directories to auto-register so OpenSpace
                    can select and track them.  Directories are re-scanned
                    on every call to discover skills created since the last
                    invocation.
    """
    try:
        openspace = await _get_openspace()

        # Re-scan host skill directories (from env) to pick up skills
        # created by the host bot since the last call.
        host_skill_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
        if host_skill_dirs_raw:
            env_dirs = [d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()]
            if env_dirs:
                await _auto_register_skill_dirs(env_dirs)

        # Auto-register bot skill directories (from call parameter)
        if skill_dirs:
            await _auto_register_skill_dirs(skill_dirs)

        # Determine where CAPTURED skills should be written.
        # Prefer the explicit skill_dirs parameter (= calling host agent's dir),
        # then fall back to the first env-based host skill dir.
        capture_skill_dir: str | None = None
        if skill_dirs:
            capture_skill_dir = skill_dirs[0]
        elif host_skill_dirs_raw:
            first_env = next(
                (d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()),
                None,
            )
            if first_env:
                capture_skill_dir = first_env

        # Execute
        result = await openspace.execute(
            task=task,
            workspace_dir=workspace_dir,
            max_iterations=max_iterations,
            capture_skill_dir=capture_skill_dir,
        )

        formatted = _format_task_result(result)
        return _json_ok(formatted)

    except Exception as e:
        logger.error(f"execute_task failed: {e}", exc_info=True)
        return _json_error(e, status="error")


@mcp.tool()
async def fix_skill(
    skill_dir: str,
    direction: str,
) -> str:
    """Manually fix a broken skill.

    This is the **only** manual evolution entry point.  DERIVED and
    CAPTURED evolutions are triggered automatically by ``execute_task``
    (they need a task to run).  Use ``fix_skill`` when:

      - A skill's instructions are wrong or outdated
      - The bot knows exactly which skill is broken and what to fix
      - Auto-evolution inside ``execute_task`` didn't catch the issue

    The skill does NOT need to be pre-registered in OpenSpace —
    provide the skill directory path and OpenSpace will register it
    automatically before fixing.

    Args:
        skill_dir: Path to the broken skill directory (must contain SKILL.md).
        direction: What's broken and how to fix it.  Be specific:
                   e.g. "The API endpoint changed from v1 to v2" or
                   "Add retry logic for HTTP 429 rate limit errors".
    """
    try:
        from openspace.skill_engine.types import EvolutionSuggestion, EvolutionType
        from openspace.skill_engine.evolver import EvolutionContext, EvolutionTrigger

        if not direction:
            return _json_error("direction is required — describe what to fix.")

        skill_path = Path(skill_dir)
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            return _json_error(f"SKILL.md not found in {skill_dir}")

        openspace = await _get_openspace()
        registry = openspace._skill_registry
        if not registry:
            return _json_error("SkillRegistry not initialized")
        if not openspace._skill_evolver:
            return _json_error("Skill evolution is not enabled")

        # Step 1: Register the skill (idempotent)
        meta = registry.register_skill_dir(skill_path)
        if not meta:
            return _json_error(f"Failed to register skill from {skill_dir}")

        store = _get_store()
        await store.sync_from_registry([meta])

        # Step 2: Load record + content
        rec = store.load_record(meta.skill_id)
        if not rec:
            return _json_error(f"Failed to load skill record for {meta.skill_id}")

        evolver = openspace._skill_evolver
        content = evolver._load_skill_content(rec)
        if not content:
            return _json_error(f"Cannot load content for skill: {meta.skill_id}")

        # Step 3: Run FIX evolution
        recent = store.load_analyses(skill_id=meta.skill_id, limit=5)

        ctx = EvolutionContext(
            trigger=EvolutionTrigger.ANALYSIS,
            suggestion=EvolutionSuggestion(
                evolution_type=EvolutionType.FIX,
                target_skill_ids=[meta.skill_id],
                direction=direction,
            ),
            skill_records=[rec],
            skill_contents=[content],
            skill_dirs=[skill_path],
            recent_analyses=recent,
            available_tools=evolver._available_tools,
        )

        logger.info(f"fix_skill: {meta.skill_id} — {direction[:100]}")
        new_record = await evolver.evolve(ctx)

        if not new_record:
            return _json_ok({
                "status": "failed",
                "error": "Evolution did not produce a new skill.",
            })

        new_skill_dir = Path(new_record.path).parent if new_record.path else skill_path
        return _json_ok({
            "status": "success",
            "new_skill": {
                "skill_dir": str(new_skill_dir),
                "name": new_record.name,
                "origin": new_record.lineage.origin.value,
                "change_summary": new_record.lineage.change_summary,
            },
        })

    except Exception as e:
        logger.error(f"fix_skill failed: {e}", exc_info=True)
        return _json_error(e, status="error")

def run_mcp_server() -> None:
    """Console-script entry point for ``openspace-mcp``."""
    import argparse

    def _port_flag_was_set(argv: list[str]) -> bool:
        return any(arg == "--port" or arg.startswith("--port=") for arg in argv)

    def _parse_port_from_env(default: int = 8080) -> int:
        raw_port = os.environ.get("OPENSPACE_MCP_PORT", "").strip()
        if not raw_port:
            return default
        try:
            return int(raw_port)
        except ValueError:
            logger.warning(
                "Ignoring invalid OPENSPACE_MCP_PORT=%r; falling back to %d.",
                raw_port,
                default,
            )
            return default

    def _parse_host_from_env(default: str = "127.0.0.1") -> str:
        return os.environ.get("OPENSPACE_MCP_HOST", "").strip() or default

    def _resolve_transport(requested_transport: str, argv: list[str]) -> str:
        if requested_transport in ("stdio", "sse", "streamable-http"):
            return requested_transport

        env_transport = os.environ.get("OPENSPACE_MCP_TRANSPORT", "").strip().lower()
        if env_transport:
            if env_transport in ("stdio", "sse", "streamable-http"):
                return env_transport
            logger.warning(
                "Ignoring invalid OPENSPACE_MCP_TRANSPORT=%r; expected 'stdio', 'sse', or 'streamable-http'.",
                env_transport,
            )

        # Treat an explicit port override as an HTTP/SSE intent. This keeps the
        # CLI behavior aligned with the usage examples above.
        if _port_flag_was_set(argv):
            return "sse"

        stdin_is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        stdout_is_tty = _real_stdout.isatty()
        return "sse" if stdin_is_tty and stdout_is_tty else "stdio"

    argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="OpenSpace MCP Server")
    parser.add_argument(
        "--transport",
        choices=["auto", "stdio", "sse", "streamable-http"],
        default="auto",
    )
    parser.add_argument("--host", default=_parse_host_from_env())
    parser.add_argument("--port", type=int, default=_parse_port_from_env())
    args = parser.parse_args(argv)

    transport = _resolve_transport(args.transport, argv)

    if transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info("Starting OpenSpace MCP server with SSE transport on port %s", args.port)
        mcp.run(transport="sse")
    elif transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info(
            "Starting OpenSpace MCP server with streamable HTTP transport on %s:%s",
            args.host,
            args.port,
        )
        mcp.run(transport="streamable-http")
    else:
        logger.info("Starting OpenSpace MCP server with stdio transport")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
