from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROOT = Path('.')
ANALYSIS = ROOT / '_analysis_phase2'
USAGE_CSV = ANALYSIS / 'MODELS_USAGE.csv'
META_CSV = ANALYSIS / 'TABLES_IN_METADATA.csv'
MIG_CSV = ANALYSIS / 'MIGRATIONS_TOUCH_MAP.csv'
CLASS_CSV = ANALYSIS / 'MODELS_CLASSIFICATION.csv'
DEAD_MD = ANALYSIS / 'DEAD_TABLES_CANDIDATES.md'
SCHEMA_MD = ANALYSIS / 'SCHEMA_TARGET_DRAFT.md'
SUMMARY_MD = ANALYSIS / 'EXEC_SUMMARY_PHASE2.md'


def set_safe_env() -> None:
    os.environ.setdefault('SECRET_KEY', 'dev')
    os.environ.setdefault('APP_DB_MODE', 'sqlite')
    os.environ.setdefault('SQLITE_PATH', 'instance/_analysis_models.db')
    os.environ.setdefault('OFFLINE_DB_PATH', 'instance/_analysis_offline.db')


def load_metadata_details():
    set_safe_env()
    try:
        from models import db  # type: ignore
    except Exception:
        from app import create_app  # type: ignore

        app = create_app()
        app.app_context().push()
        from models import db  # type: ignore

    details = {}
    for table in db.metadata.sorted_tables:
        cols = [f"{c.name}:{c.type}" for c in table.columns]
        fks = []
        for c in table.columns:
            for fk in c.foreign_keys:
                fks.append(f"{c.name}->{fk.target_fullname}")
        details[table.name] = {'columns': cols, 'fks': sorted(set(fks))}
    return details


def parse_int(v: str) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main() -> None:
    usage_rows = load_csv(USAGE_CSV)
    _ = load_csv(META_CSV)
    mig_rows = load_csv(MIG_CSV)
    meta_details = load_metadata_details()

    mig_mentions: dict[str, list[str]] = defaultdict(list)
    for r in mig_rows:
        rev = r['revision']
        merged = ';'.join([r['tables_created'], r['tables_altered'], r['tables_dropped']])
        for t in [x for x in merged.split(';') if x]:
            mig_mentions[t].append(rev)

    out_rows = []
    by_class = {'CORE': [], 'SUPPORT': [], 'LEGACY_SUSPECT': []}

    for r in usage_rows:
        name = r['table/model']
        table = name.split('/')[0]
        py = parse_int(r['python_refs'])
        tpl = parse_int(r['template_refs'])
        js = parse_int(r['js_refs'])
        tst = parse_int(r['test_refs'])
        mig = parse_int(r['migration_refs'])
        top_py = r['top_files_python']

        core_runtime = any(x in top_py for x in ['app.py', 'calendario_service.py'])
        support_paths = any(
            x in top_py for x in ['sync', 'offline', 'tools/', 'api/', 'db/']
        )

        if py >= 2 or core_runtime or tpl > 0:
            cls = 'CORE'
            rationale = f'uso runtime (py={py}, tpl={tpl}, js={js})'
        elif py > 0 and support_paths:
            cls = 'SUPPORT'
            rationale = f'uso indirecto (sync/offline/tools/api/db), py={py}'
        elif py == 0 and tpl == 0 and js == 0 and tst > 0:
            cls = 'SUPPORT'
            rationale = f'uso apenas em testes (test_refs={tst})'
        elif py == 0 and tpl == 0 and js == 0 and tst == 0 and (mig > 0 or table not in mig_mentions):
            cls = 'LEGACY_SUSPECT'
            if mig > 0:
                rationale = f'so migrations (migration_refs={mig})'
            else:
                rationale = 'sem referencias no codigo nem migrations detectadas'
        else:
            cls = 'SUPPORT'
            rationale = f'uso residual (py={py}, tpl={tpl}, js={js}, tests={tst})'

        item = {'table/model': name, 'classification': cls, 'rationale_short': rationale}
        out_rows.append(item)
        by_class[cls].append((r, item))

    with CLASS_CSV.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['table/model', 'classification', 'rationale_short']
        )
        writer.writeheader()
        writer.writerows(out_rows)

    with DEAD_MD.open('w', encoding='utf-8') as f:
        f.write('# DEAD TABLES CANDIDATES (LEGACY_SUSPECT)\n\n')
        if not by_class['LEGACY_SUSPECT']:
            f.write('Nenhuma tabela classificada como LEGACY_SUSPECT.\n')
        for row, item in by_class['LEGACY_SUSPECT']:
            table = row['table/model'].split('/')[0]
            refs = (
                f"python={row['python_refs']}, templates={row['template_refs']}, "
                f"js={row['js_refs']}, tests={row['test_refs']}, migrations={row['migration_refs']}"
            )
            f.write(f"## {row['table/model']}\n")
            f.write(f"- Classificacao: {item['classification']}\n")
            f.write(f"- Racional: {item['rationale_short']}\n")
            f.write(f"- Contagens: {refs}\n")
            examples = mig_mentions.get(table, [])[:3]
            if examples:
                f.write('- Exemplos (migrations):\n')
                for e in examples:
                    f.write(f'  - revision {e}\n')
            else:
                f.write('- Exemplos: sem ocorrencias detectadas em migrations.\n')
            f.write('\n')

    with SCHEMA_MD.open('w', encoding='utf-8') as f:
        f.write('# SCHEMA TARGET DRAFT (CORE + SUPPORT)\n\n')
        f.write('## CORE\n\n')
        for row, _item in by_class['CORE']:
            table = row['table/model'].split('/')[0]
            details = meta_details.get(table, {'columns': [], 'fks': []})
            f.write(f"### {row['table/model']}\n")
            f.write(f"- Colunas principais: {', '.join(details['columns'][:12])}\n")
            f.write(f"- Relações (FK): {', '.join(details['fks']) if details['fks'] else 'sem FKs'}\n\n")

        f.write('## SUPPORT\n\n')
        for row, _item in by_class['SUPPORT']:
            table = row['table/model'].split('/')[0]
            details = meta_details.get(table, {'columns': [], 'fks': []})
            f.write(f"### {row['table/model']}\n")
            f.write(f"- Colunas principais: {', '.join(details['columns'][:12])}\n")
            f.write(f"- Relações (FK): {', '.join(details['fks']) if details['fks'] else 'sem FKs'}\n\n")

        pg_suspects = []
        for t, details in meta_details.items():
            joined = ' '.join(details['columns']).lower()
            if any(k in joined for k in ['jsonb', 'uuid', 'array', 'bytea', 'tsvector']):
                pg_suspects.append(t)
        f.write('## Nota de compatibilidade SQLite/Postgres\n\n')
        if pg_suspects:
            f.write(
                '- Tipos potencialmente PG-only detectados nas tabelas: '
                + ', '.join(sorted(pg_suspects))
                + '.\n'
            )
        else:
            f.write('- Nao foram detectados tipos explicitamente PG-only via introspecao textual dos tipos.\n')

    total = len(usage_rows)
    core_n = len(by_class['CORE'])
    support_n = len(by_class['SUPPORT'])
    legacy_n = len(by_class['LEGACY_SUSPECT'])

    legacy_sorted = sorted(
        by_class['LEGACY_SUSPECT'], key=lambda x: parse_int(x[0]['migration_refs']), reverse=True
    )[:10]

    with SUMMARY_MD.open('w', encoding='utf-8') as f:
        f.write('# EXEC_SUMMARY_PHASE2\n\n')
        f.write('## Resumo executivo\n\n')
        f.write(f'- Total de tabelas/models em metadata: **{total}**.\n')
        f.write(f'- Classificacao CORE: **{core_n}**.\n')
        f.write(f'- Classificacao SUPPORT: **{support_n}**.\n')
        f.write(f'- Classificacao LEGACY_SUSPECT: **{legacy_n}**.\n\n')

        f.write('## Top 10 suspeitas para remocao (sem remover nesta fase)\n\n')
        if legacy_sorted:
            for row, item in legacy_sorted:
                f.write(
                    f"1. {row['table/model']} — {item['rationale_short']} "
                    f"[py={row['python_refs']}, tpl={row['template_refs']}, js={row['js_refs']}, tests={row['test_refs']}, mig={row['migration_refs']}]\n"
                )
        else:
            f.write('- Nao ha suspeitas LEGACY_SUSPECT com os criterios actuais.\n')

        f.write('\n## Riscos para baseline migration\n\n')
        f.write('- Divergencia entre uso runtime e historico de migrations pode ocultar dependencias nao visiveis.\n')
        f.write('- Tabelas apenas em migrations exigem validacao manual antes de excluir no baseline.\n')
        pg_suspects = []
        for t, details in meta_details.items():
            joined = ' '.join(details['columns']).lower()
            if any(k in joined for k in ['jsonb', 'uuid', 'array', 'bytea', 'tsvector']):
                pg_suspects.append(t)
        if pg_suspects:
            f.write(
                '- Existem tabelas com tipos possivelmente dependentes de Postgres: '
                + ', '.join(sorted(pg_suspects))
                + '.\n'
            )
        else:
            f.write('- Nao foram detectados tipos PG-only explicitos (validar constraints/triggers manualmente).\n')

    print(f'Wrote {CLASS_CSV}, {DEAD_MD}, {SCHEMA_MD}, {SUMMARY_MD}')


if __name__ == '__main__':
    main()
