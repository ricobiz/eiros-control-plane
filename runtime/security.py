from __future__ import annotations
from typing import Any
from runtime.config import load_config

VALID_MODES = {'disabled', 'operator'}

def settings() -> dict[str, Any]:
    value = load_config().get('security', {})
    return value if isinstance(value, dict) else {}

def mode() -> str:
    selected = str(settings().get('shell_mode') or 'disabled').strip().lower()
    return selected if selected in VALID_MODES else 'disabled'

def require_operator(reason: str = 'command execution') -> None:
    if mode() != 'operator':
        raise PermissionError(f'{reason} is disabled for this EIROS instance')

def local_commands_allowed() -> bool:
    value = settings()
    return mode() == 'operator' and bool(value.get('allow_local_shell_tasks', False))

def validate_local_action(action: dict[str, Any] | None) -> None:
    value = action or {}
    if str(value.get('type') or 'noop') == 'shell' and not local_commands_allowed():
        raise PermissionError('Local command queue actions are disabled for this EIROS instance')
