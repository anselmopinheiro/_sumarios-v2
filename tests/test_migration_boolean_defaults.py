import re
from pathlib import Path


def test_no_integer_server_default_on_boolean_columns_in_migrations():
    versions_dir = Path('migrations/versions')
    patterns = [
        re.compile(r"sa\.Column\([^\n]*sa\.Boolean\([^\)]*\)[^\n]*server_default\s*=\s*sa\.text\(\s*['\"](?:0|1)['\"]\s*\)", re.IGNORECASE),
        re.compile(r"sa\.Column\([^\n]*sa\.Boolean\([^\)]*\)[^\n]*server_default\s*=\s*['\"](?:0|1)['\"]", re.IGNORECASE),
        re.compile(r"sa\.Column\([^\n]*sa\.Boolean\([^\)]*\)[^\n]*server_default\s*=\s*(?:0|1)\b", re.IGNORECASE),
    ]

    offenders = []
    for path in sorted(versions_dir.glob('*.py')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for idx, line in enumerate(text.splitlines(), start=1):
            if 'sa.Boolean' not in line or 'server_default' not in line:
                continue
            if any(p.search(line) for p in patterns):
                offenders.append(f"{path}:{idx}: {line.strip()}")

    assert not offenders, "Boolean columns with integer server_default found:\n" + "\n".join(offenders)
