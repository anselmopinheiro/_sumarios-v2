# _sumarios-v2

Aplicação Flask para gestão de turmas, calendários de aulas e sumários.

## Instalação (do zero)
1. **Criar ambiente**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   ```
2. **Instalar dependências**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configurar variáveis (opcional)**
   - `FLASK_APP=app.py`
   - `FLASK_ENV=development` (para reloading automático)

4. **Criar base de dados**
   - Por omissão é usado `sqlite:///gestor_lectivo.db` na raiz do projeto.
   - Para um arranque limpo basta executar:
     ```bash
     flask db upgrade
     ```
     (a aplicação também cria as tabelas automaticamente no primeiro arranque se a BD estiver vazia).

5. **Popular dados iniciais (opcional)**
   ```bash
   python seed.py
   python seed_interrupcoes.py
   ```

6. **Executar**
   ```bash
   flask run
   ```

## Otimizações
- Índices criados para consultas frequentes sobre calendários, alunos e avaliações (melhoram listagens diárias/semanais e mapas de avaliação).
- Criação automática de tabelas e colunas recentes para reduzir falhas em instalações novas ou bases antigas.

## Importação de calendários
- Disponível em **"Importar calendário"** no menu principal.
- Aceita ficheiros JSON com uma lista de aulas ou um bloco `{"turmas": [{"turma_id"/"turma_nome", "aulas": [...]}, ...]}`.
- Opcionalmente pode ser escolhido, na página, uma turma por defeito para linhas sem turma definida.

