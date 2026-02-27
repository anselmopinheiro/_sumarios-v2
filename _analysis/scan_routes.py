import ast
import csv
import inspect
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "_analysis"
LOGS = ANALYSIS / "logs"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

FILES = {
    "routes_full": ANALYSIS / "ROUTES_FULL.csv",
    "routes_classified": ANALYSIS / "ROUTES_CLASSIFIED.csv",
    "refs_templates": ANALYSIS / "REFERENCES_TEMPLATES.csv",
    "refs_js": ANALYSIS / "REFERENCES_JS.csv",
    "broken_url_for": ANALYSIS / "BROKEN_URL_FOR.csv",
    "broken_redirects": ANALYSIS / "BROKEN_REDIRECTS.csv",
    "missing_templates": ANALYSIS / "MISSING_TEMPLATES.csv",
    "orphan_routes": ANALYSIS / "ORPHAN_ROUTES.csv",
    "duplicate_endpoints": ANALYSIS / "DUPLICATE_ENDPOINTS.csv",
    "static_hardcoded": ANALYSIS / "STATIC_HARDCODED_URLS.csv",
    "report": ANALYSIS / "FASE1_REPORT.md",
    "exec": ANALYSIS / "EXEC_SUMMARY_FASE1.md",
}


def set_safe_env():
    defaults = {
        "SECRET_KEY": "dev",
        "APP_DB_MODE": "sqlite",
        "SQLITE_PATH": "instance/_analysis_routes.db",
        "OFFLINE_DB_PATH": "_analysis_offline.db",
        "DEV_LOCAL_SCHEDULER": "0",
        "SNAPSHOT_INTERVAL_SECONDS": "999999",
        "BACKUP_ON_STARTUP": "0",
        "BACKUP_ON_COMMIT": "0",
        "FLASK_ENV": "development",
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)


def load_app():
    set_safe_env()
    sys.path.insert(0, str(ROOT))
    attempts = []
    for mode in ["create_app", "app_module", "index_app", "api_index"]:
        try:
            if mode == "create_app":
                from app import create_app

                return create_app(), "from app import create_app"
            if mode == "app_module":
                from app import app

                return app, "from app import app"
            if mode == "index_app":
                from index import app

                return app, "from index import app"
            if mode == "api_index":
                import api.index as idx

                if hasattr(idx, "create_app"):
                    return idx.create_app(), "from api.index import create_app"
                return idx.app, "from api.index import app"
        except Exception as exc:
            attempts.append((mode, exc, traceback.format_exc()))

    log_path = LOGS / "app_import_error.log"
    with log_path.open("w", encoding="utf-8") as fh:
        for mode, exc, tb in attempts:
            fh.write(f"== Attempt: {mode} ==\n{exc}\n{tb}\n\n")
    raise RuntimeError(f"Falha ao importar app. Ver: {log_path}")


def write_csv(path, rows, headers):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def dump_url_map(app):
    rows = []
    endpoint_rules = defaultdict(list)
    rules_by_path = defaultdict(list)
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        bp = rule.endpoint.split(".", 1)[0] if "." in rule.endpoint else ""
        row = {
            "rule": rule.rule,
            "methods": "|".join(methods),
            "endpoint": rule.endpoint,
            "blueprint": bp,
            "defaults": str(rule.defaults or {}),
            "arguments": "|".join(sorted(rule.arguments)),
        }
        rows.append(row)
        endpoint_rules[rule.endpoint].append(rule)
        rules_by_path[rule.rule].append(rule.endpoint)
    write_csv(FILES["routes_full"], rows, ["rule", "methods", "endpoint", "blueprint", "defaults", "arguments"])
    return rows, endpoint_rules, rules_by_path


def build_endpoint_index(app):
    idx = {}
    for endpoint, fn in app.view_functions.items():
        module = getattr(fn, "__module__", "")
        file = ""
        line = ""
        try:
            file = inspect.getsourcefile(fn) or ""
            lines, start = inspect.getsourcelines(fn)
            line = start
        except Exception:
            pass
        if file:
            rf = Path(file).resolve()
            try:
                rel_file = str(rf.relative_to(ROOT))
            except Exception:
                rel_file = str(rf)
        else:
            rel_file = ""
        idx[endpoint] = {
            "function": getattr(fn, "__name__", ""),
            "module": module,
            "file": rel_file,
            "line": line,
            "fn": fn,
        }
    return idx


def iter_files(base, suffixes=None):
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if suffixes and p.suffix.lower() not in suffixes:
            continue
        yield p


def scan_templates(endpoint_set):
    refs, broken, static_hardcoded = [], [], []
    endpoint_refs = defaultdict(set)
    path_refs = defaultdict(set)

    url_for_re = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")
    attr_re = re.compile(r"\b(href|action|src)\s*=\s*['\"]([^'\"]+)['\"]")

    for file in iter_files(TEMPLATES_DIR, {".html", ".jinja", ".j2", ".txt"}):
        rel = str(file.relative_to(ROOT))
        text = file.read_text(encoding="utf-8", errors="ignore")
        for ln, line in enumerate(text.splitlines(), start=1):
            for m in url_for_re.finditer(line):
                ep = m.group(1)
                refs.append({"kind": "url_for", "value": ep, "file": rel, "line": ln})
                endpoint_refs[ep].add((rel, ln, "url_for"))
                if ep not in endpoint_set:
                    broken.append({"endpoint": ep, "file": rel, "line": ln, "context": line.strip()[:400]})
            for m in attr_re.finditer(line):
                kind, val = m.group(1), m.group(2)
                refs.append({"kind": kind, "value": val, "file": rel, "line": ln})
                if val.startswith("/"):
                    path_refs[val].add((rel, ln, kind))
                    static_hardcoded.append({"kind": kind, "value": val, "file": rel, "line": ln})

    write_csv(FILES["refs_templates"], refs, ["kind", "value", "file", "line"])
    write_csv(FILES["broken_url_for"], broken, ["endpoint", "file", "line", "context"])
    write_csv(FILES["static_hardcoded"], static_hardcoded, ["kind", "value", "file", "line"])
    return endpoint_refs, path_refs, broken


def scan_static_js():
    rows = []
    path_refs = defaultdict(set)
    patterns = [
        re.compile(r"fetch\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"axios(?:\.[a-zA-Z]+)?\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"\$\.(?:get|post|ajax)\(\s*['\"]([^'\"]+)['\"]"),
    ]
    hardcoded = re.compile(r"['\"](/(?:api|offline|admin|turmas|calendario|health|aulas|backups|definicoes)[^'\"]*)['\"]")

    targets = list(iter_files(STATIC_DIR, {".js", ".ts"})) + list(iter_files(TEMPLATES_DIR, {".html"}))
    for file in targets:
        rel = str(file.relative_to(ROOT))
        text = file.read_text(encoding="utf-8", errors="ignore")
        for ln, line in enumerate(text.splitlines(), start=1):
            for pat in patterns:
                for m in pat.finditer(line):
                    val = m.group(1)
                    rows.append({"kind": pat.pattern.split("\\(")[0], "value": val, "file": rel, "line": ln})
                    if val.startswith("/"):
                        path_refs[val].add((rel, ln, "js"))
            for m in hardcoded.finditer(line):
                val = m.group(1)
                rows.append({"kind": "hardcoded", "value": val, "file": rel, "line": ln})
                path_refs[val].add((rel, ln, "hardcoded"))

    write_csv(FILES["refs_js"], rows, ["kind", "value", "file", "line"])
    return path_refs, rows


def rule_match_exists(path, route_rules):
    if path in route_rules:
        return True
    for rr in route_rules:
        rx = re.sub(r"<[^>]+>", "[^/]+", rr)
        if re.fullmatch(rx, path):
            return True
    return False


def scan_render_template_and_redirects(app, endpoint_index, route_rules):
    missing, broken_redirects = [], []
    redirects_to_endpoint = defaultdict(set)
    redirects_to_path = defaultdict(set)

    for endpoint, meta in endpoint_index.items():
        fn = meta["fn"]
        try:
            src = inspect.getsource(fn)
            _, start = inspect.getsourcelines(fn)
        except Exception:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        class V(ast.NodeVisitor):
            def visit_Call(self, node):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr

                if name == "render_template" and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        tpl = a0.value
                        if not (TEMPLATES_DIR / tpl).exists():
                            missing.append({
                                "endpoint": endpoint,
                                "template": tpl,
                                "file": meta["file"],
                                "line": start + node.lineno - 1,
                                "dynamic": "no",
                            })
                    else:
                        missing.append({
                            "endpoint": endpoint,
                            "template": "<dynamic>",
                            "file": meta["file"],
                            "line": start + node.lineno - 1,
                            "dynamic": "yes",
                        })

                if name == "redirect" and node.args:
                    a0 = node.args[0]
                    line_no = start + node.lineno - 1
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        target = a0.value
                        if target.startswith("/") and not rule_match_exists(target, route_rules):
                            broken_redirects.append({
                                "source_endpoint": endpoint,
                                "target": target,
                                "file": meta["file"],
                                "line": line_no,
                                "reason": "path_nao_existe",
                            })
                        redirects_to_path[target].add((endpoint, meta["file"], line_no))
                    elif isinstance(a0, ast.Call):
                        fname = None
                        if isinstance(a0.func, ast.Name):
                            fname = a0.func.id
                        elif isinstance(a0.func, ast.Attribute):
                            fname = a0.func.attr
                        if fname == "url_for" and a0.args and isinstance(a0.args[0], ast.Constant):
                            ep = a0.args[0].value
                            redirects_to_endpoint[ep].add((endpoint, meta["file"], line_no))
                self.generic_visit(node)

        V().visit(tree)

    # keep dynamic entries in separate non-breaking way
    missing_fixed = [m for m in missing if m["template"] != "<dynamic>"]
    write_csv(FILES["missing_templates"], missing_fixed, ["endpoint", "template", "file", "line", "dynamic"])
    write_csv(FILES["broken_redirects"], broken_redirects, ["source_endpoint", "target", "file", "line", "reason"])
    return missing_fixed, broken_redirects, redirects_to_endpoint, redirects_to_path


def detect_duplicate_endpoints(routes_full):
    by_endpoint = defaultdict(list)
    for r in routes_full:
        by_endpoint[r["endpoint"]].append(r)
    dups = []
    for ep, items in by_endpoint.items():
        if len(items) <= 1:
            continue
        keys = {(i["rule"], i["methods"]) for i in items}
        status = "duplicate_exact" if len(keys) < len(items) else "multi_rule_same_endpoint"
        for i in items:
            dups.append({"endpoint": ep, "rule": i["rule"], "methods": i["methods"], "status": status})
    write_csv(FILES["duplicate_endpoints"], dups, ["endpoint", "rule", "methods", "status"])
    return dups




def path_ref_matches_rule(rule, refs_map):
    if rule in refs_map:
        return True

    rx = re.sub(r"<[^>]+>", "[^/]+", rule)
    for ref_path in refs_map.keys():
        if not isinstance(ref_path, str) or not ref_path.startswith('/'):
            continue

        normalized = re.sub(r"\$\{[^}]+\}", "1", ref_path)
        if re.fullmatch(rx, normalized):
            return True
    return False


def classify_routes(routes_full, endpoint_refs, template_path_refs, js_path_refs, redirects_to_endpoint, broken_url_for, missing_templates, broken_redirects):
    broken_eps = set([r["endpoint"] for r in missing_templates])
    broken_eps |= set()
    b_redirect_sources = {r["source_endpoint"] for r in broken_redirects}
    broken_url_for_set = {r["endpoint"] for r in broken_url_for}

    classified = []
    orphans = []

    for r in routes_full:
        ep = r["endpoint"]
        rule = r["rule"]
        has_template_ref = bool(endpoint_refs.get(ep)) or path_ref_matches_rule(rule, template_path_refs)
        has_js_ref = path_ref_matches_rule(rule, js_path_refs)
        has_redirect_in = bool(redirects_to_endpoint.get(ep))
        is_offline = rule.startswith("/offline")
        is_health = ("/health" in rule) or ("ping" in rule)
        is_static = ep == "static" or rule.startswith("/static/")

        status = "ORPHAN"
        action = "avaliar_remocao_ou_documentacao"

        if ep in broken_eps or ep in b_redirect_sources or ep in broken_url_for_set:
            status = "BROKEN"
            action = "corrigir_referencias/template/redirect"
        elif has_template_ref:
            status = "OK_UI"
            action = "manter"
        elif has_js_ref:
            status = "OK_API"
            action = "manter"
        elif is_health or is_static or rule.startswith("/api/") or rule.startswith("/admin") or rule.startswith("/definicoes/") or rule.startswith("/backups"):
            status = "INTERNAL"
            action = "documentar_interno"
        elif is_offline:
            status = "OK_UI"
            action = "manter"
        elif has_redirect_in:
            status = "INTERNAL"
            action = "documentar_fluxo"

        row = {
            "rule": rule,
            "methods": r["methods"],
            "endpoint": ep,
            "blueprint": r["blueprint"],
            "has_template_ref": int(has_template_ref),
            "has_js_ref": int(has_js_ref),
            "has_redirect_in": int(has_redirect_in),
            "is_offline": int(is_offline),
            "is_health": int(is_health),
            "is_static": int(is_static),
            "classification": status,
            "action": action,
        }
        classified.append(row)
        if status == "ORPHAN":
            orphans.append(row)

    write_csv(FILES["routes_classified"], classified, list(classified[0].keys()) if classified else [])
    write_csv(FILES["orphan_routes"], orphans, list(orphans[0].keys()) if orphans else ["rule", "methods", "endpoint", "blueprint", "has_template_ref", "has_js_ref", "has_redirect_in", "is_offline", "is_health", "is_static", "classification", "action"])
    return classified, orphans


def generate_reports(import_mode, routes_full, endpoint_index, classified, broken_url_for, missing_templates, broken_redirects, dups, orphan_routes, js_rows):
    by_bp = Counter(r["blueprint"] or "(root)" for r in routes_full)
    by_methods = Counter()
    for r in routes_full:
        for m in filter(None, r["methods"].split("|")):
            by_methods[m] += 1
    by_class = Counter(r["classification"] for r in classified)

    orphan_with_src = []
    for o in orphan_routes[:50]:
        idx = endpoint_index.get(o["endpoint"], {})
        src = f"{idx.get('file','')}:{idx.get('line','')}"
        orphan_with_src.append((o["rule"], o["endpoint"], src))

    hardcoded_suspicious = [r for r in js_rows if r["kind"] == "hardcoded"][:20]

    report = []
    report.append("# FASE 1 — Auditoria de routes e destino visível\n")
    report.append(f"Import mode: `{import_mode}`\n")
    report.append("## 1) Estatísticas\n")
    report.append(f"- Total routes: **{len(routes_full)}**")
    report.append("- Por blueprint:")
    for bp, n in by_bp.most_common():
        report.append(f"  - `{bp}`: {n}")
    report.append("- Por método:")
    for m, n in by_methods.most_common():
        report.append(f"  - `{m}`: {n}")
    report.append("- Por classificação:")
    for c, n in by_class.most_common():
        report.append(f"  - `{c}`: {n}")

    report.append("\n## 2) Top riscos (até 20 por categoria)\n")
    report.append(f"- BROKEN url_for: {len(broken_url_for)}")
    for r in broken_url_for[:20]:
        report.append(f"  - {r['endpoint']} em {r['file']}:{r['line']}")
    report.append(f"- Missing templates: {len(missing_templates)}")
    for r in missing_templates[:20]:
        report.append(f"  - {r['template']} (endpoint={r['endpoint']}) em {r['file']}:{r['line']}")
    report.append(f"- Redirects inválidos: {len(broken_redirects)}")
    for r in broken_redirects[:20]:
        report.append(f"  - {r['source_endpoint']} -> {r['target']} em {r['file']}:{r['line']}")
    report.append(f"- Hardcoded URLs suspeitos (JS/templates): {len(hardcoded_suspicious)} mostrados")
    for r in hardcoded_suspicious:
        report.append(f"  - {r['value']} em {r['file']}:{r['line']}")

    report.append("\n## 3) Top 50 routes órfãs\n")
    report.append("| rule | endpoint | view file:line | nota |")
    report.append("|---|---|---|---|")
    for rule, ep, src in orphan_with_src:
        report.append(f"| `{rule}` | `{ep}` | `{src}` | sem origem detectada por heurística |")

    report.append("\n## 4) Ações sugeridas\n")
    report.append("1. Corrigir `url_for` inválidos e alinhar nomes de endpoint.")
    report.append("2. Corrigir `redirect('/...')` para `url_for(...)` quando aplicável.")
    report.append("3. Rever links hardcoded em templates/JS, privilegiando `url_for`.")
    report.append("4. Documentar endpoints internos (health/api/admin técnico).")
    report.append("5. Validar remoção de órfãs após confirmação funcional.")

    report.append("\n## 5) Destino visível — método e limites\n")
    report.append("- Inferido por referências a endpoint/path em templates (`url_for`, `href`, `action`, `src`), JS (`fetch/axios/jquery`) e redirects entre views.")
    report.append("- Limites: chamadas dinâmicas (string construída), navegação por dados externos, e rotas usadas apenas via CLI/integradores podem aparecer como órfãs.")

    FILES["report"].write_text("\n".join(report) + "\n", encoding="utf-8")

    p0 = len(broken_url_for) + len(missing_templates) + len(broken_redirects)
    p1 = len(orphan_routes)
    p2 = len(dups)
    exec_lines = [
        "# EXEC_SUMMARY_FASE1",
        "",
        "## Resumo executivo (pt-PT)",
        f"1. A análise foi feita por introspeção real do `url_map` (sem depender do README), usando `create_app()` com envs seguros de análise.",
        f"2. Foram inventariadas **{len(routes_full)} routes** e classificadas por origem visível (UI, JS/API, interno, órfã, quebrada).",
        f"3. Resultado de classificação: " + ", ".join([f"{k}={v}" for k, v in Counter(r['classification'] for r in classified).most_common()]) + ".",
        f"4. Foram detetados **{len(broken_url_for)} url_for inválidos**, **{len(missing_templates)} templates em falta** e **{len(broken_redirects)} redirects inválidos**.",
        f"5. Foram assinaladas **{len(orphan_routes)} routes órfãs** (sem origem visível por heurística estática).",
        f"6. Endpoints internos (health/static/api técnica) foram separados de órfãs para evitar falso positivo funcional.",
        f"7. Foram recolhidas referências em templates e JS para suportar decisão de limpeza/refactor com rastreabilidade.",
        f"8. Risco P0 atual: {p0} achados de quebra direta de navegação/resolução (url_for/template/redirect).",
        f"9. Risco P1 atual: {p1} órfãs que requerem validação funcional antes de remover/documentar.",
        f"10. Risco P2 atual: {p2} potenciais duplicações/colisões de endpoint para revisão de higiene de rotas.",
        "",
        "## Priorização",
        f"- **P0**: corrigir quebras objetivas (`BROKEN_URL_FOR`, `MISSING_TEMPLATES`, `BROKEN_REDIRECTS`) antes de alterações estruturais.",
        f"- **P1**: validar e reduzir órfãs (remover ou documentar como internas).",
        f"- **P2**: harmonizar links hardcoded e eventuais endpoints duplicados.",
        "",
        "## Próximos passos recomendados",
        "1. Corrigir referências quebradas e voltar a correr `scan_routes.py` até P0=0.",
        "2. Introduzir regra de estilo: evitar redirects hardcoded (`redirect('/x')`) e preferir `url_for`.",
        "3. Consolidar mapa de navegação (menu + páginas de acesso indireto) para reduzir órfãs reais.",
        "4. Antes do refactor de migrations, estabilizar superfície de routes para não migrar endpoints mortos.",
        "",
        "## Nota",
        "- Esta fase não executa servidor nem faz requests HTTP reais; é análise estática + introspeção do `url_map`.",
    ]
    FILES["exec"].write_text("\n".join(exec_lines) + "\n", encoding="utf-8")


def main():
    app, import_mode = load_app()
    routes_full, endpoint_rules, route_rules = dump_url_map(app)
    endpoint_index = build_endpoint_index(app)
    endpoint_set = set(endpoint_rules.keys())

    endpoint_refs, template_path_refs, broken_url_for = scan_templates(endpoint_set)
    js_path_refs, js_rows = scan_static_js()
    missing_templates, broken_redirects, redirects_to_endpoint, _ = scan_render_template_and_redirects(app, endpoint_index, route_rules)
    dups = detect_duplicate_endpoints(routes_full)
    classified, orphan_routes = classify_routes(
        routes_full,
        endpoint_refs,
        template_path_refs,
        js_path_refs,
        redirects_to_endpoint,
        broken_url_for,
        missing_templates,
        broken_redirects,
    )
    generate_reports(import_mode, routes_full, endpoint_index, classified, broken_url_for, missing_templates, broken_redirects, dups, orphan_routes, js_rows)


if __name__ == "__main__":
    main()
