from __future__ import annotations

import ast
import csv
import os
import sys
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from typing import Iterable

ROOT = Path('.')
ANALYSIS_DIR = ROOT / '_analysis_phase2'
TABLES_CSV = ANALYSIS_DIR / 'TABLES_IN_METADATA.csv'
OUT_CSV = ANALYSIS_DIR / 'MODELS_USAGE.csv'

PYTHON_EXTS = {'.py'}
TEMPLATE_EXTS = {'.html', '.jinja', '.j2'}
JS_EXTS = {'.js', '.mjs', '.cjs', '.ts'}


def set_safe_env() -> None:
    os.environ.setdefault('SECRET_KEY', 'dev')
    os.environ.setdefault('APP_DB_MODE', 'sqlite')
    os.environ.setdefault('SQLITE_PATH', 'instance/_analysis_models.db')
    os.environ.setdefault('OFFLINE_DB_PATH', 'instance/_analysis_offline.db')


def load_tables() -> list[str]:
    with TABLES_CSV.open(newline='', encoding='utf-8') as f:
        return [row['table_name'] for row in csv.DictReader(f)]


def load_model_map() -> dict[str, str]:
    set_safe_env()
    table_to_model: dict[str, str] = {}
    try:
        import models  # type: ignore
    except Exception:
        from app import create_app  # type: ignore

        app = create_app()
        app.app_context().push()
        import models  # type: ignore

    for name, obj in vars(models).items():
        if isinstance(obj, type) and hasattr(obj, '__tablename__'):
            table = getattr(obj, '__tablename__', None)
            if isinstance(table, str):
                table_to_model[table] = name

    # fallback via AST
    if not table_to_model:
        source = Path('models.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                tablename = None
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if isinstance(t, ast.Name) and t.id == '__tablename__':
                                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                    tablename = stmt.value.value
                if tablename:
                    table_to_model[tablename] = node.name

    return table_to_model


def collect_files() -> dict[str, list[Path]]:
    py_targets: list[Path] = []
    for p in ROOT.rglob('*.py'):
        s = p.as_posix()
        if s.startswith('.git/') or s.startswith('.venv/') or '/.venv/' in s:
            continue
        if s.startswith('_analysis_phase2/'):
            continue
        py_targets.append(p)

    templates = [p for p in (ROOT / 'templates').rglob('*') if p.is_file()]
    js = [p for p in (ROOT / 'static').rglob('*') if p.is_file()]
    tests = [p for p in (ROOT / 'tests').rglob('*') if p.is_file()] if (ROOT / 'tests').exists() else []
    migrations = [p for p in (ROOT / 'migrations' / 'versions').rglob('*.py')] if (ROOT / 'migrations' / 'versions').exists() else []

    return {
        'python': [p for p in py_targets if p.suffix in PYTHON_EXTS],
        'templates': [p for p in templates if p.suffix in TEMPLATE_EXTS or p.name.endswith('.html')],
        'js': [p for p in js if p.suffix in JS_EXTS],
        'tests': [p for p in tests if p.suffix in PYTHON_EXTS],
        'migrations': migrations,
    }


def to_patterns(table: str, model: str | None) -> list[re.Pattern[str]]:
    pats = [
        re.compile(rf'\b{re.escape(table)}\b'),
        re.compile(rf'ForeignKey\(["\"]{re.escape(table)}\.'),
        re.compile(rf'__tablename__\s*=\s*["\"]{re.escape(table)}["\"]'),
    ]
    if model:
        pats.extend(
            [
                re.compile(rf'\b{re.escape(model)}\b'),
                re.compile(rf'\b{re.escape(model)}\.'),
                re.compile(rf'relationship\(["\"][^"\
]*{re.escape(model)}'),
                re.compile(rf'db\.session\.query\(\s*{re.escape(model)}\s*\)'),
            ]
        )
    return pats


def count_refs(patterns: Iterable[re.Pattern[str]], files: list[Path]) -> tuple[int, Counter[str]]:
    total = 0
    per_file: Counter[str] = Counter()
    for p in files:
        try:
            text = p.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            text = p.read_text(encoding='latin-1', errors='ignore')
        cnt = 0
        for pat in patterns:
            cnt += len(pat.findall(text))
        if cnt:
            rel = p.as_posix().removeprefix('./')
            per_file[rel] = cnt
            total += cnt
    return total, per_file


def top_files(counter: Counter[str]) -> str:
    return '; '.join(f"{f}:{c}" for f, c in counter.most_common(5))


def main() -> None:
    tables = load_tables()
    model_map = load_model_map()
    files = collect_files()

    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'table/model',
            'python_refs',
            'template_refs',
            'js_refs',
            'test_refs',
            'migration_refs',
            'top_files_python',
            'top_files_templates',
            'top_files_js',
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for table in sorted(tables):
            model = model_map.get(table)
            patterns = to_patterns(table, model)
            py_count, py_files = count_refs(patterns, files['python'])
            tpl_count, tpl_files = count_refs(patterns, files['templates'])
            js_count, js_files = count_refs(patterns, files['js'])
            test_count, _ = count_refs(patterns, files['tests'])
            mig_count, _ = count_refs(patterns, files['migrations'])

            writer.writerow(
                {
                    'table/model': f"{table}/{model or ''}".strip('/'),
                    'python_refs': py_count,
                    'template_refs': tpl_count,
                    'js_refs': js_count,
                    'test_refs': test_count,
                    'migration_refs': mig_count,
                    'top_files_python': top_files(py_files),
                    'top_files_templates': top_files(tpl_files),
                    'top_files_js': top_files(js_files),
                }
            )

    print(f'Wrote usage analysis to {OUT_CSV}')


if __name__ == '__main__':
    main()
