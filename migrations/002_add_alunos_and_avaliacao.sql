CREATE TABLE IF NOT EXISTS alunos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  turma_id INT NOT NULL,
  processo VARCHAR(50) NULL,
  numero INT NULL,
  nome VARCHAR(255) NOT NULL,
  nome_curto VARCHAR(100) NULL,
  nee TEXT NULL,
  observacoes TEXT NULL,
  INDEX ix_alunos_turma_numero (turma_id, numero),
  CONSTRAINT fk_alunos_turma FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS aulas_alunos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  aula_id INT NOT NULL,
  aluno_id INT NOT NULL,
  atraso TINYINT(1) NOT NULL DEFAULT 0,
  faltas INT NOT NULL DEFAULT 0,
  responsabilidade INT NOT NULL DEFAULT 3,
  comportamento INT NOT NULL DEFAULT 3,
  participacao INT NOT NULL DEFAULT 3,
  trabalho_autonomo INT NOT NULL DEFAULT 3,
  portatil_material INT NOT NULL DEFAULT 3,
  atividade INT NOT NULL DEFAULT 3,
  falta_disciplinar INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_aula_aluno (aula_id, aluno_id),
  INDEX ix_aulas_alunos_aula (aula_id),
  INDEX ix_aulas_alunos_aluno (aluno_id),
  CONSTRAINT fk_aulas_alunos_aula FOREIGN KEY (aula_id) REFERENCES calendario_aulas(id) ON DELETE CASCADE,
  CONSTRAINT fk_aulas_alunos_aluno FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schema_version(version) VALUES ('002_add_alunos_and_avaliacao');
