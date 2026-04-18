# Sumários v2 — README Operacional (Codex)

## 1. Objetivo da aplicação

A aplicação **Sumários v2** é uma plataforma de gestão de aulas e avaliação escolar.

Funcionalidades principais:

* Gestão de aulas (sumários)
* Registo de faltas
* Avaliação de alunos (EV2):

  * perfis por turma
  * domínios
  * rubricas
  * componentes (subdivisão interna da rubrica)
* Avaliação por aula, observação direta, portfólio, projetos e trabalhos

Princípios fundamentais:

* A **rubrica é a unidade principal de avaliação**
* Os **componentes são internos à rubrica**
* A avaliação é **quantitativa primeiro**, com possibilidade de gerar feedback depois
* Compatibilidade obrigatória: **SQLite ↔ PostgreSQL**

---

## 2. Regras obrigatórias para o Codex

### 2.1. Âmbito das alterações

* Fazer **apenas o que é pedido**
* Não refatorar código sem instrução explícita
* Não alterar lógica existente sem necessidade clara
* Não introduzir novas abstrações sem validação

---

### 2.2. Validação obrigatória antes de terminar

Nunca considerar a tarefa concluída sem:

1. Verificar sintaxe:

   ```
   python -m py_compile $(git ls-files '*.py')
   ```

2. Executar:

   ```
   flask db upgrade
   ```

3. Confirmar:

   * a app arranca
   * não há erros no console
   * a funcionalidade pedida está operacional

Se falhar:

* corrigir antes de terminar
* não entregar código com erros

---

### 2.3. Base de dados

* Garantir compatibilidade:

  * SQLite
  * PostgreSQL (Supabase)

Regras:

* evitar features específicas de PostgreSQL
* usar:

  * `sa.Enum(native_enum=False)` ou `String`
* usar migrations seguras:

  * `batch_alter_table` quando necessário
* não usar índices específicos de um dialeto

---

### 2.4. EV2 (avaliação)

Regras estruturais obrigatórias:

* Rubrica:

  * unidade principal de avaliação
* Componentes:

  * não têm peso
  * pertencem a uma rubrica
  * têm descritores próprios (N1..N5)
* Se a rubrica tem componentes:

  * não tem descritores próprios
* Nota da rubrica:

  * média simples dos componentes
* Não criar lógica paralela ou duplicada

---

### 2.5. Frontend / UI

* Não alterar layout sem pedido explícito
* Preferir:

  * soluções simples
  * reutilização de templates
* Evitar:

  * JS complexo desnecessário
  * duplicação de lógica

---

### 2.6. Git (obrigatório)

Após cada tarefa concluída e validada:

1. Verificar estado:

   ```
   git status
   ```

2. Adicionar alterações:

   ```
   git add .
   ```

3. Commit:

   ```
   git commit -m "descrição curta e objetiva da alteração"
   ```

4. Push:

   ```
   git push origin <branch_atual>
   ```

Regras:

* Nunca fazer commit em `main`
* Trabalhar sempre em branch
* Não terminar tarefa sem push

---

### 2.7. Diagnóstico antes de alterar

Se existir erro:

* identificar primeiro a causa exata
* não aplicar soluções genéricas
* não tentar “várias coisas”
* propor correção mínima

---

### 2.8. Código

* Evitar duplicação
* Não deixar código morto
* Não deixar blocos incompletos
* Garantir indentação correta
* Garantir imports válidos

---

## 3. O que NÃO fazer

* Não inventar funcionalidades
* Não alterar comportamento sem pedido
* Não simplificar removendo partes críticas
* Não ignorar erros
* Não terminar sem validar

---

## 4. Critério de conclusão

Uma tarefa só está concluída quando:

* não há erros de sintaxe
* migrations executam
* a funcionalidade funciona
* não há regressões
* código está commitado e em push

---

## 5. Filosofia de desenvolvimento

* Simplicidade > complexidade
* Correção > rapidez
* Alteração mínima > refatoração global
* Testar sempre antes de concluir

```
```
