# Migração para PHP + MySQL (fase inicial)

## Estado atual
Esta pasta contém a primeira fase funcional da reimplementação em PHP puro:
- autenticação simples por sessão
- dashboard
- gestão básica de turmas
- calendário por turma com edição de sumário/previsão em modal
- importação CSV de turmas com dry-run e pré-visualização (20 linhas)

## Estrutura
- `public/index.php` front controller
- `src/` config, DB PDO, auth/csrf, router, controllers, repositories, services
- `views/` layout + páginas
- `storage/logs` logs de erro
- `storage/exports` exportações CSV
- `schema.sql` + `migrations/*.sql`

## Configuração
1. Criar base MySQL (`utf8mb4_unicode_ci`).
2. Executar `schema.sql` no phpMyAdmin.
3. Opcional: executar `migrations/002_add_alunos_and_avaliacao.sql`.
4. Criar `.env` na raiz com:

```
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=sumarios
DB_USER=utilizador
DB_PASS=senha
APP_USER=admin
APP_PASSWORD_HASH=$2y$10$substituir_por_hash_real
```

Gerar hash com `password_hash('AQUI_A_TUA_SENHA', PASSWORD_DEFAULT)` localmente.

## Deploy FTP (cPanel)
1. Subir o conteúdo do repositório por FTP.
2. Definir document root para `public/`.
3. Garantir permissões de escrita em `storage/logs` e `storage/exports`.
4. Configurar base de dados no cPanel e atualizar `.env`.

## Importar CSV
- Ir a `/importar`
- Escolher tabela `turmas`
- Definir separador (`;` ou `,`)
- Executar em `dry-run` para validar
- Executar em `import` para gravar

CSV esperado para turmas (cabeçalhos):
`nome;tipo;periodo_tipo`

## Próximas fases
- disciplinas, livros, anos letivos e calendário escolar
- direção de turma e avaliação diária
- exportações completas CSV/JSON
- importador CSV multi-tabela com mapeamento de colunas e relatório avançado
