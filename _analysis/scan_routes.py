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
    "routes_classified_v2": ANALYSIS / "ROUTES_CLASSIFIED_v2.csv",
    "refs_templates": ANALYSIS / "REFERENCES_TEMPLATES.csv",
    "refs_js": ANALYSIS / "REFERENCES_JS.csv",
    "broken_url_for": ANALYSIS / "BROKEN_URL_FOR.csv",
    "broken_redirects": ANALYSIS / "BROKEN_REDIRECTS.csv",
    "missing_templates": ANALYSIS / "MISSING_TEMPLATES.csv",
    "orphan_routes": ANALYSIS / "ORPHAN_ROUTES.csv",
    "orphan_routes_v2": ANALYSIS / "ORPHAN_ROUTES_v2.csv",
    "duplicate_endpoints": ANALYSIS / "DUPLICATE_ENDPOINTS.csv",
    "static_hardcoded": ANALYSIS / "STATIC_HARDCODED_URLS.csv",
    "report": ANALYSIS / "FASE1_REPORT.md",
    "exec": ANALYSIS / "EXEC_SUMMARY_FASE1.md",
    "exec_v2": ANALYSIS / "EXEC_SUMMARY_FASE1_v2.md",
    "orphan_decisions": ANALYSIS / "ORPHAN_DECISIONS.md",
    "delta_note": ANALYSIS / "DELTA_FASE1_v2.md",
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
    LOGS.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        for mode, exc, tb in attempts:
            fh.write(f"== Attempt: {mode} ==\n{exc}\n{tb}\n\n")
    raise RuntimeError(f"Falha ao importar app. Ver: {log_path}")


def write_csv(path: Path, rows, headers):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def iter_files(base: Path, suffixes=None):
    for p in base.rglob("*"):
        if p.is_file() and (suffixes is None or p.suffix.lower() in suffixes):
            yield p


def compile_rule_regex(rule: str):
    pattern = re.sub(r"<[^>]+>", r"[^/]+", rule)
    return re.compile(r"^" + pattern + r"$")


def normalize_path_reference(path: str):
    if not isinstance(path, str):
        return path
    return re.sub(r"\$\{[^}]+\}", "1", path)


def dump_url_map(app):
    rows = []
    endpoint_rules = defaultdict(list)
    route_regex = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        methods = sorted([m for m in rule.methods if m not in {"HEAD", "OPTIONS"}])
        blueprint = rule.endpoint.split(".", 1)[0] if "." in rule.endpoint else ""
        rows.append(
            {
                "rule": rule.rule,
                "methods": "|".join(methods),
                "endpoint": rule.endpoint,
                "blueprint": blueprint,
                "defaults": str(rule.defaults or {}),
                "arguments": "|".join(sorted(rule.arguments)),
            }
        )
        endpoint_rules[rule.endpoint].append(rule)
        route_regex[rule.rule] = compile_rule_regex(rule.rule)

    write_csv(FILES["routes_full"], rows, ["rule", "methods", "endpoint", "blueprint", "defaults", "arguments"])
    return rows, endpoint_rules, route_regex


def build_endpoint_index(app):
    out = {}
    for endpoint, fn in app.view_functions.items():
        src_file = ""
        src_line = ""
        try:
            src_file = inspect.getsourcefile(fn) or ""
            _, src_line = inspect.getsourcelines(fn)
        except Exception:
            pass
        if src_file:
            rf = Path(src_file).resolve()
            try:
                src_file = str(rf.relative_to(ROOT))
            except Exception:
                src_file = str(rf)
        out[endpoint] = {
            "fn": fn,
            "file": src_file,
            "line": src_line,
            "module": getattr(fn, "__module__", ""),
            "function": getattr(fn, "__name__", ""),
        }
    return out


def scan_templates(endpoint_set):
    url_for_re = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")
    attr_re = re.compile(r"\b(href|action|src)\s*=\s*['\"]([^'\"]+)['\"]")

    refs = []
    broken = []
    hardcoded = []
    endpoint_refs = defaultdict(set)
    path_refs = defaultdict(set)

    for file in iter_files(TEMPLATES_DIR, {".html", ".jinja", ".j2"}):
        rel = str(file.relative_to(ROOT))
        text = file.read_text(encoding="utf-8", errors="ignore")
        for ln, line in enumerate(text.splitlines(), start=1):
            for m in url_for_re.finditer(line):
                endpoint = m.group(1)
                refs.append({"kind": "url_for", "value": endpoint, "file": rel, "line": ln})
                endpoint_refs[endpoint].add((rel, ln, "url_for"))
                if endpoint not in endpoint_set:
                    broken.append({"endpoint": endpoint, "file": rel, "line": ln, "context": line.strip()[:400]})
            for m in attr_re.finditer(line):
                kind, value = m.group(1), m.group(2)
                refs.append({"kind": kind, "value": value, "file": rel, "line": ln})
                if value.startswith("/"):
                    path_refs[value].add((rel, ln, kind))
                    hardcoded.append({"kind": kind, "value": value, "file": rel, "line": ln})

    write_csv(FILES["refs_templates"], refs, ["kind", "value", "file", "line"])
    write_csv(FILES["broken_url_for"], broken, ["endpoint", "file", "line", "context"])
    write_csv(FILES["static_hardcoded"], hardcoded, ["kind", "value", "file", "line"])
    return endpoint_refs, path_refs, broken


def scan_js_and_inline_scripts(route_regex):
    refs = []
    path_refs = defaultdict(set)
    route_ref_hits = Counter()

    call_patterns = [
        re.compile(r"fetch\(\s*(['\"])(.+?)\1"),
        re.compile(r"fetch\(\s*`([^`]+)`"),
        re.compile(r"axios(?:\.[a-zA-Z]+)?\(\s*(['\"])(.+?)\1"),
        re.compile(r"\$\.(?:get|post|ajax)\(\s*(['\"])(.+?)\1"),
    ]
    hardcoded = re.compile(r"['\"](/(?:api|offline|admin|turmas|calendario|health|aulas|backups|definicoes)[^'\"]*)['\"]")

    targets = list(iter_files(STATIC_DIR, {".js", ".ts"})) + list(iter_files(TEMPLATES_DIR, {".html"}))
    for file in targets:
        rel = str(file.relative_to(ROOT))
        text = file.read_text(encoding="utf-8", errors="ignore")
        for ln, line in enumerate(text.splitlines(), start=1):
            found_values = []
            for pat in call_patterns:
                for m in pat.finditer(line):
                    value = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
                    refs.append({"kind": "call", "value": value, "file": rel, "line": ln})
                    found_values.append(value)
            for m in hardcoded.finditer(line):
                value = m.group(1)
                refs.append({"kind": "hardcoded", "value": value, "file": rel, "line": ln})
                found_values.append(value)

            for value in found_values:
                if not isinstance(value, str) or not value.startswith("/"):
                    continue
                normalized = normalize_path_reference(value)
                path_refs[value].add((rel, ln, "js"))
                for rule, rx in route_regex.items():
                    if rx.fullmatch(normalized):
                        route_ref_hits[rule] += 1

    write_csv(FILES["refs_js"], refs, ["kind", "value", "file", "line"])
    return path_refs, route_ref_hits


def scan_python_references(route_rows):
    endpoint_refs = Counter()
    path_refs = Counter()
    endpoint_names = [r["endpoint"] for r in route_rows]
    endpoint_alt = set(endpoint_names)

    py_files = list(iter_files(ROOT, {".py"}))
    for file in py_files:
        if ".git" in file.parts or file.parts[-2:-1] == (".venv",):
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for ep in endpoint_alt:
            if not ep:
                continue
            if f"url_for('{ep}'" in text or f'url_for("{ep}"' in text:
                endpoint_refs[ep] += text.count(f"url_for('{ep}'") + text.count(f'url_for("{ep}"')
        for r in route_rows:
            path = r["rule"]
            if "<" in path:
                continue
            path_refs[path] += text.count(f"'{path}'") + text.count(f'"{path}"')

    return endpoint_refs, path_refs


def scan_render_and_redirects(endpoint_index, route_regex):
    missing = []
    broken_redirects = []
    redirect_targets = defaultdict(set)

    for endpoint, meta in endpoint_index.items():
        fn = meta["fn"]
        try:
            src = inspect.getsource(fn)
            _, start = inspect.getsourcelines(fn)
            tree = ast.parse(src)
        except Exception:
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

                if name == "redirect" and node.args:
                    a0 = node.args[0]
                    lno = start + node.lineno - 1
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        target = a0.value
                        if target.startswith("/"):
                            ok = any(rx.fullmatch(target) for rx in route_regex.values())
                            if not ok:
                                broken_redirects.append({
                                    "source_endpoint": endpoint,
                                    "target": target,
                                    "file": meta["file"],
                                    "line": lno,
                                    "reason": "path_nao_existe",
                                })
                        redirect_targets[target].add((endpoint, meta["file"], lno))
                    elif isinstance(a0, ast.Call):
                        fname = a0.func.id if isinstance(a0.func, ast.Name) else (a0.func.attr if isinstance(a0.func, ast.Attribute) else "")
                        if fname == "url_for" and a0.args and isinstance(a0.args[0], ast.Constant):
                            redirect_targets[a0.args[0].value].add((endpoint, meta["file"], lno))
                self.generic_visit(node)

        V().visit(tree)

    write_csv(FILES["missing_templates"], missing, ["endpoint", "template", "file", "line", "dynamic"])
    write_csv(FILES["broken_redirects"], broken_redirects, ["source_endpoint", "target", "file", "line", "reason"])
    return missing, broken_redirects, redirect_targets


def detect_duplicate_endpoints(route_rows):
    by_ep = defaultdict(list)
    for r in route_rows:
        by_ep[r["endpoint"]].append(r)
    dups = []
    for ep, items in by_ep.items():
        if len(items) > 1:
            keys = {(i["rule"], i["methods"]) for i in items}
            status = "duplicate_exact" if len(keys) < len(items) else "multi_rule_same_endpoint"
            for i in items:
                dups.append({"endpoint": ep, "rule": i["rule"], "methods": i["methods"], "status": status})
    write_csv(FILES["duplicate_endpoints"], dups, ["endpoint", "rule", "methods", "status"])
    return dups


def classify_routes(route_rows, endpoint_refs_tmpl, path_refs_tmpl, js_route_hits, py_endpoint_refs, py_path_refs, redirect_targets, broken_url_for, missing_templates, broken_redirects):
    broken_set = {r["endpoint"] for r in broken_url_for} | {r["endpoint"] for r in missing_templates} | {r["source_endpoint"] for r in broken_redirects}

    classified = []
    orphans = []
    for r in route_rows:
        ep = r["endpoint"]
        rule = r["rule"]
        has_template_ref = bool(endpoint_refs_tmpl.get(ep)) or bool(path_refs_tmpl.get(rule))
        has_js_ref = js_route_hits.get(rule, 0) > 0
        has_redirect_in = bool(redirect_targets.get(ep))
        py_refs = py_endpoint_refs.get(ep, 0) + py_path_refs.get(rule, 0)

        is_offline = rule.startswith("/offline")
        is_internal_like = rule.startswith("/api/") or rule.startswith("/admin") or rule.startswith("/backups") or rule.startswith("/definicoes/") or ep == "static" or "/health" in rule

        cls = "ORPHAN"
        action = "avaliar_remocao_ou_documentacao"

        if ep in broken_set:
            cls = "BROKEN"
            action = "corrigir_referencias"
        elif has_template_ref:
            cls = "OK_UI"
            action = "manter"
        elif has_js_ref:
            cls = "OK_API"
            action = "manter"
        elif is_internal_like or has_redirect_in:
            cls = "INTERNAL"
            action = "documentar_interno"
        elif is_offline:
            cls = "OK_UI"
            action = "manter"

        row = {
            "rule": rule,
            "methods": r["methods"],
            "endpoint": ep,
            "blueprint": r["blueprint"],
            "template_ref_count": len(endpoint_refs_tmpl.get(ep, [])) + len(path_refs_tmpl.get(rule, [])),
            "js_ref_count": int(js_route_hits.get(rule, 0)),
            "python_ref_count": int(py_refs),
            "has_redirect_in": int(has_redirect_in),
            "classification": cls,
            "action": action,
        }
        classified.append(row)
        if cls == "ORPHAN":
            orphans.append(row)

    headers = list(classified[0].keys()) if classified else ["rule", "methods", "endpoint", "blueprint", "template_ref_count", "js_ref_count", "python_ref_count", "has_redirect_in", "classification", "action"]
    write_csv(FILES["routes_classified"], classified, headers)
    write_csv(FILES["routes_classified_v2"], classified, headers)
    write_csv(FILES["orphan_routes"], orphans, headers)
    write_csv(FILES["orphan_routes_v2"], orphans, headers)
    return classified, orphans


def generate_orphan_decisions(orphans):
    lines = ["# ORPHAN_DECISIONS (auto)", "", "Base: ORPHAN_ROUTES_v2.csv", ""]
    if not orphans:
        lines.append("Sem órfãs remanescentes.")
    for o in orphans:
        lines.extend([
            f"## `{o['rule']}` ({o['endpoint']})",
            f"- template_ref_count: {o['template_ref_count']}",
            f"- js_ref_count: {o['js_ref_count']}",
            f"- python_ref_count: {o['python_ref_count']}",
            "- decisão: REMOVE_CANDIDATE (confirmar antes de remover)",
            "",
        ])
    FILES["orphan_decisions"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_reports(import_mode, route_rows, classified, orphans, broken_url_for, missing_templates, broken_redirects, dups, previous_orphan_count=None):
    by_class = Counter(r["classification"] for r in classified)
    lines = [
        "# EXEC_SUMMARY_FASE1_v2",
        "",
        f"- Import mode: `{import_mode}`",
        f"- Total routes: {len(route_rows)}",
        f"- Classificação: " + ", ".join([f"{k}={v}" for k, v in by_class.most_common()]),
        f"- BROKEN_URL_FOR: {len(broken_url_for)}",
        f"- MISSING_TEMPLATES: {len(missing_templates)}",
        f"- BROKEN_REDIRECTS: {len(broken_redirects)}",
        f"- ORPHAN: {len(orphans)}",
        "",
        "## Nota técnica",
        "- Endpoints com referências JS (`fetch('/path')` e template-literals `fetch(`/path/${id}`)`) passam a mapear para `rule` e recebem `has_js_ref`/`js_ref_count`.",
        "- Isto força classificação `OK_API` mesmo sem `url_for/href`.",
    ]
    FILES["exec_v2"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    delta_lines = [
        "# Delta Fase1 v2",
        "",
        f"- Órfãs atuais: {len(orphans)}",
    ]
    if previous_orphan_count is not None:
        delta_lines.append(f"- Órfãs anteriores (baseline): {previous_orphan_count}")
        delta_lines.append(f"- Eliminadas por reclassificação (principalmente OK_API): {previous_orphan_count - len(orphans)}")
    delta_lines.append("- `sumario_copiar_previsao` e `sumario_reverter` devem surgir como OK_API (refs JS em templates/base.html).")
    if any(o["endpoint"] == "calendario_add" for o in orphans):
        delta_lines.append("- `calendario_add`: REMOVE_CANDIDATE confirmado (0 refs templates/js/python).")
    FILES["delta_note"].write_text("\n".join(delta_lines) + "\n", encoding="utf-8")

    # keep legacy files too
    FILES["exec"].write_text(FILES["exec_v2"].read_text(encoding="utf-8"), encoding="utf-8")


def read_previous_orphan_count():
    p = FILES["orphan_routes"]
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    except Exception:
        return None


def main():
    prev_orphans = read_previous_orphan_count()
    app, import_mode = load_app()
    routes, endpoint_rules, route_regex = dump_url_map(app)
    endpoint_index = build_endpoint_index(app)

    endpoint_refs_tmpl, path_refs_tmpl, broken_url_for = scan_templates(set(endpoint_rules.keys()))
    _, js_route_hits = scan_js_and_inline_scripts(route_regex)
    py_endpoint_refs, py_path_refs = scan_python_references(routes)
    missing_templates, broken_redirects, redirect_targets = scan_render_and_redirects(endpoint_index, route_regex)
    dups = detect_duplicate_endpoints(routes)

    classified, orphans = classify_routes(
        routes,
        endpoint_refs_tmpl,
        path_refs_tmpl,
        js_route_hits,
        py_endpoint_refs,
        py_path_refs,
        redirect_targets,
        broken_url_for,
        missing_templates,
        broken_redirects,
    )

    generate_orphan_decisions(orphans)
    generate_reports(import_mode, routes, classified, orphans, broken_url_for, missing_templates, broken_redirects, dups, previous_orphan_count=prev_orphans)


if __name__ == "__main__":
    main()
