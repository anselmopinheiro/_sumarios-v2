# FASE 1 — Auditoria de routes e destino visível

Import mode: `from app import create_app`

## 1) Estatísticas

- Total routes: **138**
- Por blueprint:
  - `(root)`: 124
  - `offline`: 14
- Por método:
  - `POST`: 87
  - `GET`: 80
  - `DELETE`: 1
- Por classificação:
  - `OK_UI`: 119
  - `ORPHAN`: 13
  - `INTERNAL`: 5
  - `OK_API`: 1

## 2) Top riscos (até 20 por categoria)

- BROKEN url_for: 8
  - disciplinas_add em templates/disciplinas/gestao.html:7
  - disciplinas_edit em templates/disciplinas/gestao.html:22
  - disciplinas_delete em templates/disciplinas/gestao.html:24
  - disciplinas_gestao em templates/disciplinas/form.html:24
  - calendario_dia em templates/admin/calendario_diario.html:5
  - turma_disciplinas em templates/turmas/gestao.html:32
  - turmas_gestao em templates/turmas/disciplinas.html:6
  - disciplinas_gestao em templates/turmas/disciplinas.html:11
- Missing templates: 0
- Redirects inválidos: 0
- Hardcoded URLs suspeitos (JS/templates): 7 mostrados
  - /offline/errors/clear em templates/offline_dashboard.html:426
  - /calendario/semana em templates/base.html:136
  - /calendario/dia em templates/base.html:137
  - /turmas em templates/base.html:139
  - /admin em templates/base.html:142
  - /offline/status?format=json em templates/base.html:880
  - /calendario/sumarios-pendentes em templates/turmas/sumarios_pendentes.html:37

## 3) Top 50 routes órfãs

| rule | endpoint | view file:line | nota |
|---|---|---|---|
| `/admin/anos-letivos` | `admin_anos_letivos` | `app.py:3110` | sem origem detectada por heurística |
| `/admin/calendario-diario` | `admin_calendario_diario` | `app.py:3122` | sem origem detectada por heurística |
| `/admin/calendario-semanal` | `admin_calendario_semanal` | `app.py:3116` | sem origem detectada por heurística |
| `/admin/direcao-turma` | `admin_direcao_turma` | `app.py:3162` | sem origem detectada por heurística |
| `/admin/disciplinas-dt` | `admin_disciplinas_dt` | `app.py:3168` | sem origem detectada por heurística |
| `/admin/offline` | `admin_offline` | `app.py:3174` | sem origem detectada por heurística |
| `/admin/tipos-aula` | `admin_tipos_aula` | `app.py:3187` | sem origem detectada por heurística |
| `/admin/turmas` | `admin_turmas` | `app.py:3156` | sem origem detectada por heurística |
| `/aulas/<int:aula_id>/sumario/copiar-previsao` | `sumario_copiar_previsao` | `app.py:3455` | sem origem detectada por heurística |
| `/aulas/<int:aula_id>/sumario/reverter` | `sumario_reverter` | `app.py:3483` | sem origem detectada por heurística |
| `/backups` | `backups_list` | `app.py:3423` | sem origem detectada por heurística |
| `/definicoes/tipos-aula` | `definicoes_tipos_aula` | `app.py:3192` | sem origem detectada por heurística |
| `/turmas/<int:turma_id>/calendario/add` | `calendario_add` | `app.py:7327` | sem origem detectada por heurística |

## 4) Ações sugeridas

1. Corrigir `url_for` inválidos e alinhar nomes de endpoint.
2. Corrigir `redirect('/...')` para `url_for(...)` quando aplicável.
3. Rever links hardcoded em templates/JS, privilegiando `url_for`.
4. Documentar endpoints internos (health/api/admin técnico).
5. Validar remoção de órfãs após confirmação funcional.

## 5) Destino visível — método e limites

- Inferido por referências a endpoint/path em templates (`url_for`, `href`, `action`, `src`), JS (`fetch/axios/jquery`) e redirects entre views.
- Limites: chamadas dinâmicas (string construída), navegação por dados externos, e rotas usadas apenas via CLI/integradores podem aparecer como órfãs.
