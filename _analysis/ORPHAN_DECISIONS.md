# ORPHAN_DECISIONS (Fase 1)

Base: `_analysis/ORPHAN_ROUTES.csv` após correções P0.

## 1) `/aulas/<int:aula_id>/sumario/copiar-previsao` (`sumario_copiar_previsao`)
- **Decisão:** `OK_API`
- **Justificação:** endpoint acionado por JS no template base via `fetch(`/aulas/${aulaId}/sumario/copiar-previsao`)`.
- **Evidência:** `templates/base.html` linhas 423-431.
- **Ação nesta PR:** sem remover rota; classificar como endpoint de ação JS (não menu).

## 2) `/aulas/<int:aula_id>/sumario/reverter` (`sumario_reverter`)
- **Decisão:** `OK_API`
- **Justificação:** endpoint acionado por JS no template base via `fetch(`/aulas/${aulaId}/sumario/reverter`)`.
- **Evidência:** `templates/base.html` linhas 651-657.
- **Ação nesta PR:** sem remover rota; classificar como endpoint de ação JS (não menu).

## 3) `/turmas/<int:turma_id>/calendario/add` (`calendario_add`)
- **Decisão:** `REMOVE_CANDIDATE` (P1, pendente validação funcional)
- **Justificação:** não foi encontrada origem visível em templates, JS nem chamadas Python `url_for('calendario_add')`.
- **Evidência:** ausência de correspondências em `REFERENCES_TEMPLATES.csv`, `REFERENCES_JS.csv` e pesquisa de código.
- **Ação nesta PR:** manter rota; documentar como candidata a remoção para fase de limpeza.

## Nota
- Nesta PR não há remoção de rotas, apenas correções de quebras e clarificação de visibilidade.
