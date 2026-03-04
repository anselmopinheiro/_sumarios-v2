# EXEC_SUMMARY_PHASE2

## Resumo executivo

- Total de tabelas/models em metadata: **34**.
- Classificacao CORE: **34**.
- Classificacao SUPPORT: **0**.
- Classificacao LEGACY_SUSPECT: **0**.

## Top 10 suspeitas para remocao (sem remover nesta fase)

- Nao ha suspeitas LEGACY_SUSPECT com os criterios actuais.

## Riscos para baseline migration

- Divergencia entre uso runtime e historico de migrations pode ocultar dependencias nao visiveis.
- Tabelas apenas em migrations exigem validacao manual antes de excluir no baseline.
- Nao foram detectados tipos PG-only explicitos (validar constraints/triggers manualmente).
