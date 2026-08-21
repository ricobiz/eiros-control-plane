from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path('/opt/eiros-control-plane')
LIVE_ROOT = ROOT / '.worktrees/sum-auto-wake'
MAIN_OPENAI_CONTROL_PLANE = ROOT / 'runtime/openai_control_plane.py'
MAIN_VPS_OPS = ROOT / 'runtime/vps_ops_server.py'

# The live SUM branch owns the current EBRIDGE/SAM/widget implementation, while
# all durable state stays in the canonical /opt/eiros-control-plane checkout.
os.environ.setdefault('EIROS_DATA_DIR', str(ROOT))
sys.path.insert(0, str(LIVE_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from runtime import server_v2 as live_server  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load module {name} from {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The SUM worktree predates the latest OpenAI/VPS control-plane module. Load the
# current implementation explicitly without changing the live runtime package.
_load_module('runtime.openai_control_plane', MAIN_OPENAI_CONTROL_PLANE)
main_vps_ops = _load_module('eiros_main_vps_ops_server', MAIN_VPS_OPS)

mcp = FastMCP(
    'EIROS Claude Operator',
    instructions=(
        'Full Rico-authorized EIROS operator surface for Claude. It combines the live '
        'SUM/SAM/Room/Listener EBRIDGE implementation with the latest VPS Ops root/git/'
        'systemd/OpenAI control-plane tools. Read status before mutation, preserve live '
        'Room/Listener/PiP surfaces unless a repair requires replacement, test before '
        'service restarts, never expose secrets, and never force-push without explicit '
        'Rico authorization.'
    ),
    stateless_http=True,
    json_response=True,
    host='127.0.0.1',
    port=8796,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=['127.0.0.1', '127.0.0.1:*', 'localhost', 'localhost:*'],
        allowed_origins=[
            'https://claude.ai',
            'https://www.claude.ai',
            'https://claude.com',
            'https://www.claude.com',
            'http://127.0.0.1',
            'http://127.0.0.1:*',
            'http://localhost',
            'http://localhost:*',
        ],
    ),
    warn_on_duplicate_tools=False,
    warn_on_duplicate_resources=False,
    warn_on_duplicate_prompts=False,
)


def _mirror_tools(source: FastMCP[Any]) -> None:
    for tool in source._tool_manager.list_tools():
        mcp.add_tool(
            tool.fn,
            name=tool.name,
            title=tool.title,
            description=tool.description,
            annotations=tool.annotations,
            icons=tool.icons,
            meta=tool.meta,
        )


def _mirror_resources(source: FastMCP[Any]) -> None:
    for resource in source._resource_manager.list_resources():
        mcp.add_resource(resource)
    for template in source._resource_manager.list_templates():
        mcp._resource_manager._templates.setdefault(template.uri_template, template)


def _mirror_prompts(source: FastMCP[Any]) -> None:
    for prompt in source._prompt_manager.list_prompts():
        mcp._prompt_manager._prompts.setdefault(prompt.name, prompt)


# Live EBRIDGE wins duplicate names. Current VPS Ops contributes all unique
# privileged/operator tools, including root_exec and OpenAI tunnel management.
_mirror_tools(live_server.mcp)
_mirror_tools(main_vps_ops.mcp)
_mirror_resources(live_server.mcp)
_mirror_prompts(live_server.mcp)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--list-tools', action='store_true')
    parser.add_argument('--list-resources', action='store_true')
    args = parser.parse_args()
    if args.list_tools:
        print(json.dumps(sorted(tool.name for tool in mcp._tool_manager.list_tools())))
        return
    if args.list_resources:
        print(json.dumps(sorted(str(resource.uri) for resource in mcp._resource_manager.list_resources())))
        return
    mcp.run(transport='streamable-http')


if __name__ == '__main__':
    main()
