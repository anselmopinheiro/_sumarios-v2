# EXEC_SUMMARY_FASE1

## Resumo executivo (pt-PT)
1. A análise foi feita por introspeção real do `url_map` (sem depender do README), usando `create_app()` com envs seguros de análise.
2. Foram inventariadas **138 routes** e classificadas por origem visível (UI, JS/API, interno, órfã, quebrada).
3. Resultado de classificação: OK_UI=118, INTERNAL=15, ORPHAN=3, OK_API=2.
4. Foram detetados **0 url_for inválidos**, **0 templates em falta** e **0 redirects inválidos**.
5. Foram assinaladas **3 routes órfãs** (sem origem visível por heurística estática).
6. Endpoints internos (health/static/api técnica) foram separados de órfãs para evitar falso positivo funcional.
7. Foram recolhidas referências em templates e JS para suportar decisão de limpeza/refactor com rastreabilidade.
8. Risco P0 atual: 0 achados de quebra direta de navegação/resolução (url_for/template/redirect).
9. Risco P1 atual: 3 órfãs que requerem validação funcional antes de remover/documentar.
10. Risco P2 atual: 4 potenciais duplicações/colisões de endpoint para revisão de higiene de rotas.

## Priorização
- **P0**: corrigir quebras objetivas (`BROKEN_URL_FOR`, `MISSING_TEMPLATES`, `BROKEN_REDIRECTS`) antes de alterações estruturais.
- **P1**: validar e reduzir órfãs (remover ou documentar como internas).
- **P2**: harmonizar links hardcoded e eventuais endpoints duplicados.

## Próximos passos recomendados
1. Corrigir referências quebradas e voltar a correr `scan_routes.py` até P0=0.
2. Introduzir regra de estilo: evitar redirects hardcoded (`redirect('/x')`) e preferir `url_for`.
3. Consolidar mapa de navegação (menu + páginas de acesso indireto) para reduzir órfãs reais.
4. Antes do refactor de migrations, estabilizar superfície de routes para não migrar endpoints mortos.

## Nota
- Esta fase não executa servidor nem faz requests HTTP reais; é análise estática + introspeção do `url_map`.
