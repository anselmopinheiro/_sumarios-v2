from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path('.')
MIG_DIR = ROOT / 'migrations' / 'versions'
OUT_CSV = ROOT / '_analysis_phase2' / 'MIGRATIONS_TOUCH_MAP.csv'

REV_RE = re.compile(r"revision\s*=\s*['\"]([^'\"]+)['\"]")
CREATE_RE = re.compile(r"op\.create_table\(\s*['\"]([^'\"]+)['\"]")
DROP_RE = re.compile(r"op\.drop_table\(\s*['\"]([^'\"]+)['\"]")
ALTER_RE = re.compile(
    r"op\.(?:add_column|drop_column|alter_column|create_index|drop_index|create_foreign_key|drop_constraint)\(\s*['\"][^'\"]*['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
ALTER_RE_NO_INDEX_NAME = re.compile(
    r"op\.(?:add_column|drop_column|alter_column)\(\s*['\"]([^'\"]+)['\"]"
)
INDEX_RE = re.compile(r"op\.(?:create_index|drop_index)\([^\n]*['\"]([^'\"]+)['\"]\s*\)")


def parse_file(path: Path) -> dict[str, str]:
    text = path.read_text(encoding='utf-8', errors='ignore')
    rev = REV_RE.search(text)
    revision = rev.group(1) if rev else path.stem

    created = sorted(set(CREATE_RE.findall(text)))
    dropped = sorted(set(DROP_RE.findall(text)))

    altered = set(ALTER_RE.findall(text))
    altered.update(ALTER_RE_NO_INDEX_NAME.findall(text))

    for idx_line in re.finditer(r"op\.(?:create_index|drop_index)\(([^\)]*)\)", text):
        args = idx_line.group(1)
        m = re.search(r"['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", args)
        if m:
            altered.add(m.group(2))

    return {
        'revision': revision,
        'tables_created': ';'.join(created),
        'tables_altered': ';'.join(sorted(altered)),
        'tables_dropped': ';'.join(dropped),
    }


def main() -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = [parse_file(p) for p in sorted(MIG_DIR.glob('*.py'))]
    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['revision', 'tables_created', 'tables_altered', 'tables_dropped'],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f'Wrote {len(rows)} migration rows to {OUT_CSV}')


if __name__ == '__main__':
    main()
