# AGENTS.md — Regras Operacionais Obrigatórias

## Regra global

Se qualquer regra deste ficheiro não for cumprida, a tarefa não está concluída.

---

## Âmbito

- Fazer apenas o que foi pedido.
- Não alterar código fora do âmbito.
- Não refatorar sem pedido explícito.
- Não introduzir novas funcionalidades sem autorização.

---

## Fluxo obrigatório

### 1. Implementar
- Implementar a alteração pedida com delta mínimo.

### 2. Validar sintaxe
Executar:
python -m py_compile $(git ls-files '*.py')

Se existir erro:
- corrigir
- repetir este passo

### 3. Validar migrations
Executar:
flask db upgrade

Se existir erro:
- identificar causa
- corrigir
- repetir este passo

### 4. Executar a app
- Iniciar a aplicação.
- Verificar:
  - sem erros no console
  - sem erros de import
  - sem erros de rota

### 5. Validar funcionalmente
- Validar exatamente o que foi pedido.
- Não validar “parcialmente”.
- Não assumir que funciona.

### 6. Validar UI
Se a tarefa alterar templates, CSS, JS, tabelas ou layout visual:
- arrancar a app localmente
- correr o teste Playwright da página afetada
- confirmar que a página abre
- tirar screenshot
- só depois concluir

Se o teste não existir:
- criar ou adaptar um teste mínimo para a página alterada

### 7. Git
Executar:
git status
git add .
git commit -m "descrição curta e objetiva"
git push origin <branch_atual>

Regras:
- nunca usar main
- nunca terminar sem push
- git status deve ficar limpo no fim

---

## Base de dados

- Suportar SQLite e PostgreSQL.
- Proibido usar features exclusivas de PostgreSQL.
- Usar sa.Enum(native_enum=False) ou String quando aplicável.
- Manter migrations compatíveis com ambos.

---

## Persistência

- Nunca implementar autosave.
- Todas as alterações ficam em estado “por guardar”.
- Apenas o botão Guardar persiste dados.
- Não alterar payload de save sem pedido explícito.
- Não alterar estrutura de dados existente sem necessidade real.

---

## EV2 — Regras estruturais

### Rubrica
- É a unidade principal.

### Componentes
- Não têm peso.
- Pertencem a uma rubrica.
- Têm descritores próprios.

### Regra crítica
Se existirem componentes:
- a rubrica não tem descritores próprios

### Cálculo
- Nota da rubrica = média simples dos componentes.

---

## Avaliação EV2

- Componentes são a fonte de verdade.
- A rubrica é apenas agregação ou atalho.

### Cópia entre domínios
- Só copiar rubricas compatíveis.
- Compatibilidade validada por código.
- Só copiar componentes se estrutura 100% equivalente.
- Nunca copiar parcialmente.

### Overrides
- Nunca sobrescrever valores alterados manualmente.
- Preservar sempre overrides.

### Preenchimento automático
- Apenas caixas vazias:
  - 3 (básico)
  - 10 (secundário)
- Nunca sobrescrever valores existentes.
- Nunca fazer autosave.

---

## Grelha de avaliação (UX)

### Navegação
- Setas, Enter, Tab

### Atalhos
- 0–9 → definir valor
- Delete / Backspace → limpar
- + / - → ajustar valor

Regras:
- Não fazem save automático
- Apenas alteram estado local

---

## UI / Frontend

- Não alterar layout sem pedido.
- Não introduzir JS complexo sem necessidade.
- Não duplicar lógica.
- Não declarar validação visual sem browser ou Playwright.

---

## Git / Artefactos

- Nunca versionar:
  - tests/.runtime/
  - playwright-report/
  - test-results/
  - __pycache__/
  - node_modules/

- Respeitar .gitignore
- Evitar problemas de line endings

---

## README (Obrigatório)

Sempre que houver alteração funcional:

- Atualizar README.md com:
  - descrição da funcionalidade
  - instruções de uso
  - exemplos (se aplicável)

- Nunca concluir tarefa sem atualizar README quando necessário.

---

## Diagnóstico

- Identificar causa exata antes de alterar
- Não fazer tentativas aleatórias

---

## Proibições

- Código incompleto
- Código duplicado
- Código morto
- Alterações fora do pedido
- Commits sem validação

---

## Critério de conclusão

- Sem erros de sintaxe
- Migrations OK
- App arranca
- Funcionalidade validada
- Sem regressões
- Commit feito
- Push feito

---

## Regra final

Se existir dúvida:
- parar
- não assumir
- não inventar
