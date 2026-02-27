# EXEC_SUMMARY_FASE1_v2

- Import mode: `from app import create_app`
- Total routes: 137
- Classificação: OK_UI=117, INTERNAL=16, OK_API=4
- BROKEN_URL_FOR: 0
- MISSING_TEMPLATES: 0
- BROKEN_REDIRECTS: 0
- ORPHAN: 0

## Nota técnica
- Endpoints com referências JS (`fetch('/path')` e template-literals `fetch(`/path/${id}`)`) passam a mapear para `rule` e recebem `has_js_ref`/`js_ref_count`.
- Isto força classificação `OK_API` mesmo sem `url_for/href`.
