# Remoção segura da rota `calendario_add`

## Before / After
- Total routes antes: **138** (baseline Fase 1 v2).
- Total routes depois: **137**.
- ORPHAN depois: **0**.
- BROKEN_URL_FOR depois: **0**.
- MISSING_TEMPLATES depois: **0**.
- BROKEN_REDIRECTS depois: **0**.

## Validação de dependências
- Endpoint `calendario_add` removido de `app.py`.
- Procura de referências (`templates`, `JS`, `url_for`, chamadas diretas) não encontrou usos ativos antes da remoção (já estava como `REMOVE_CANDIDATE` na fase anterior).
- Helpers usados na função removida não foram removidos porque continuam referenciados por outras rotas (`calendario_edit`, `api_sync_apply`, etc.).

## Diff principal
Ver `git diff` de `app.py`: remoção do bloco da rota
`@app.route("/turmas/<int:turma_id>/calendario/add", methods=["GET", "POST"])`
e função `calendario_add(turma_id)`.
