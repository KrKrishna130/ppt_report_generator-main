"""Repair placeholder values in numeric settings without changing credentials.

Run from the project root: python3 scripts/fix_env.py
An existing .env is backed up before any repair. Valid custom values are kept.
"""
import ast
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def numeric_defaults():
    tree = ast.parse((ROOT / 'app' / 'config.py').read_text(encoding='utf-8'))
    defaults = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and isinstance(node.annotation, ast.Name)
                and node.annotation.id in ('int', 'float')
                and isinstance(node.value, ast.Constant)):
            defaults[node.target.id.upper()] = str(node.value.value)
    return defaults


def repair(path):
    defaults = numeric_defaults()
    lines, changed = [], []
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            normalized = key.strip().removeprefix('export ').upper()
            bare = value.split(' #', 1)[0].strip().strip('\"\'')
            if normalized in defaults and bare in {'change-me', 'not-needed'}:
                line = key + '=' + defaults[normalized]
                changed.append(normalized)
        lines.append(line)
    if changed:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        backup = path.with_name(path.name + '.before-token-fix-' + stamp)
        shutil.copy2(path, backup)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print('Backup created:', backup.name)
        print('Repaired numeric settings:', ', '.join(changed))
    else:
        print('No numeric placeholder repairs needed.')
    return changed


def main():
    path = ROOT / '.env'
    if not path.is_file():
        print('No .env found. Copy .env.example to .env first.', file=sys.stderr)
        return 1
    repair(path)
    print('Recreate containers: docker compose up -d --force-recreate api worker')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
