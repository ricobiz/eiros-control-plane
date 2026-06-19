from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
required_files = [
    root / 'CORE.md',
    root / 'state.json',
    root / 'JOURNAL.md',
    root / 'PROTOCOL.md',
    root / 'tasks' / 'core-bootstrap-001.json',
]
required_dirs = [root / 'tasks', root / 'logs', root / 'memory', root / 'runtime']
errors = []

for path in required_files:
    if not path.is_file():
        errors.append(f'missing file: {path.relative_to(root)}')

for path in required_dirs:
    if not path.is_dir():
        errors.append(f'missing directory: {path.relative_to(root)}')

for path in [root / 'state.json', root / 'tasks' / 'core-bootstrap-001.json']:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            errors.append(f'invalid root object: {path.relative_to(root)}')
    except Exception as exc:
        errors.append(f'invalid json {path.relative_to(root)}: {exc}')

core = (root / 'CORE.md').read_text(encoding='utf-8') if (root / 'CORE.md').exists() else ''
for phrase in [
    'current ChatGPT conversation',
    'not a separate API model',
    'Avoid infinite loops',
    'Persistent execution and state live server-side',
]:
    if phrase not in core:
        errors.append(f'CORE.md missing invariant: {phrase}')

result = {
    'ok': not errors,
    'root': str(root),
    'errors': errors,
    'files': [str(path.relative_to(root)) for path in required_files if path.exists()],
}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['ok'] else 1)
