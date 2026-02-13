# Sumários em PHP (deploy cPanel + FTP)

## Estrutura segura para alojamento partilhado

- `public/` → conteúdo para `public_html/sumarios/`
  - `index.php`
  - `.htaccess`
- `apps/sumarios/` → conteúdo para pasta fora do público (`/apps/sumarios/`)
  - `src/`
  - `views/`
  - `config/`
  - `storage/`
  - `migrations/` e scripts SQL

Com esta organização, ficheiros de aplicação fora de `public_html` não ficam acessíveis por URL.

## Deploy

1. Copiar `public/*` para `public_html/sumarios/`.
2. Copiar `apps/sumarios/*` para `/apps/sumarios/` (fora do web root).
3. Editar `/apps/sumarios/config/config.php`:
   - credenciais MySQL
   - `base_path` = `/sumarios`
4. Criar base de dados MySQL e executar `schema.sql` (via phpMyAdmin).
5. Abrir `https://meudominio.com/sumarios`.

## Rotas implementadas

- `/sumarios/` dashboard
- `/sumarios/turmas`
- `/sumarios/calendario`
- `/sumarios/aula/{id}/editar`
- `/sumarios/importar`

## CSV Import

Funcionalidade disponível em `/sumarios/importar`:
- upload de ficheiro
- validação de cabeçalhos obrigatórios: `nome`, `tipo`, `periodo_tipo`
- pré-visualização de 20 linhas
- modo `dry-run`
- modo `import`
- relatório de erros por linha

## Apache

`public/.htaccess` usa:
- `RewriteBase /sumarios/`
- front controller em `index.php`

