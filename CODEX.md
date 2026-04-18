# CODEX.md — Regras Operacionais Obrigatórias

## ⚠️ REGRA GLOBAL

SE QUALQUER REGRA DESTE DOCUMENTO NÃO FOR CUMPRIDA, A TAREFA NÃO ESTÁ CONCLUÍDA.

---

## 1. ÂMBITO

* FAZER APENAS O QUE FOI PEDIDO
* NÃO ALTERAR CÓDIGO FORA DO ÂMBITO
* NÃO REFATORAR SEM PEDIDO EXPLÍCITO
* NÃO INTRODUZIR NOVAS FUNCIONALIDADES

---

## 2. FLUXO OBRIGATÓRIO

### PASSO 1 — IMPLEMENTAR

* Implementar a alteração pedida

### PASSO 2 — VALIDAR SINTAXE (OBRIGATÓRIO)

Executar:

```
python -m py_compile $(git ls-files '*.py')
```

SE EXISTIR ERRO:

* CORRIGIR
* REPETIR ESTE PASSO

---

### PASSO 3 — MIGRATIONS (OBRIGATÓRIO)

Executar:

```
flask db upgrade
```

SE EXISTIR ERRO:

* IDENTIFICAR CAUSA
* CORRIGIR
* REPETIR ESTE PASSO

---

### PASSO 4 — EXECUÇÃO (OBRIGATÓRIO)

* INICIAR A APLICAÇÃO
* VERIFICAR:

  * SEM ERROS NO CONSOLE
  * SEM ERROS DE IMPORT
  * SEM ERROS DE ROTA

SE EXISTIR ERRO:

* CORRIGIR
* REPETIR

---

### PASSO 5 — VALIDAÇÃO FUNCIONAL (OBRIGATÓRIO)

VALIDAR EXATAMENTE O QUE FOI PEDIDO

* NÃO VALIDAR “PARCIALMENTE”
* NÃO ASSUMIR QUE FUNCIONA

SE NÃO FUNCIONAR:

* CORRIGIR
* REPETIR

---

### PASSO 6 — GIT (OBRIGATÓRIO)

Executar:

```
git status
git add .
git commit -m "descrição curta e objetiva"
git push origin <branch_atual>
```

REGRAS:

* NUNCA usar `main`
* NUNCA terminar sem `push`

---

## 3. BASE DE DADOS

* SUPORTAR:

  * SQLite
  * PostgreSQL

PROIBIDO:

* features exclusivas de PostgreSQL

OBRIGATÓRIO:

* `sa.Enum(native_enum=False)` ou `String`
* migrations compatíveis com ambos

---

## 4. EV2 — REGRAS ESTRUTURAIS

### RUBRICA

* É a unidade principal

### COMPONENTES

* NÃO têm peso
* PERTENCEM a uma rubrica
* TÊM descritores próprios

### REGRA CRÍTICA

SE EXISTIREM COMPONENTES:

* A RUBRICA NÃO TEM DESCRITORES

### CÁLCULO

* NOTA DA RUBRICA = MÉDIA SIMPLES DOS COMPONENTES

---

## 5. UI / FRONTEND

* NÃO ALTERAR layout sem pedido
* NÃO INTRODUZIR JS COMPLEXO
* NÃO DUPLICAR LÓGICA

---

## 6. DIAGNÓSTICO

ANTES DE ALTERAR:

* IDENTIFICAR A CAUSA EXATA
* NÃO FAZER TENTATIVAS ALEATÓRIAS
* NÃO APLICAR SOLUÇÕES GENÉRICAS

---

## 7. PROIBIÇÕES

NÃO FAZER:

* código incompleto
* código duplicado
* código morto
* alterações fora do pedido
* commits sem validação

---

## 8. CRITÉRIO DE CONCLUSÃO

UMA TAREFA SÓ TERMINA SE:

* NÃO EXISTEM ERROS DE SINTAXE
* MIGRATIONS EXECUTAM
* APP ARRANCA
* FUNCIONALIDADE FUNCIONA
* NÃO EXISTEM REGRESSÕES
* CÓDIGO FOI COMMITADO
* CÓDIGO FOI PUSH

---

## 9. REGRA FINAL

SE EXISTIR DÚVIDA:

* PARAR
* NÃO ASSUMIR
* NÃO INVENTAR

```
---

Isto agora está num nível que:
- reduz bastante comportamento “criativo” do Codex  
- força ciclo fechado (implementa → testa → valida → commit)  
- impede exatamente os erros que tiveste (indentação, syntax, etc.)  

---
