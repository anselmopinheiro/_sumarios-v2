CREATE TABLE IF NOT EXISTS schema_version (
  version VARCHAR(50) PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS anos_letivos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(20) NOT NULL UNIQUE,
  data_inicio_ano DATE NOT NULL,
  data_fim_ano DATE NOT NULL,
  data_fim_semestre1 DATE NOT NULL,
  data_inicio_semestre2 DATE NOT NULL,
  descricao VARCHAR(255) NULL,
  ativo TINYINT(1) NOT NULL DEFAULT 0,
  fechado TINYINT(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS turmas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(50) NOT NULL,
  tipo VARCHAR(20) NOT NULL DEFAULT 'regular',
  periodo_tipo VARCHAR(20) NOT NULL DEFAULT 'anual',
  ano_letivo_id INT NULL,
  letiva TINYINT(1) NOT NULL DEFAULT 1,
  carga_segunda DECIMAL(5,2) NULL,
  carga_terca DECIMAL(5,2) NULL,
  carga_quarta DECIMAL(5,2) NULL,
  carga_quinta DECIMAL(5,2) NULL,
  carga_sexta DECIMAL(5,2) NULL,
  tempo_segunda INT NULL,
  tempo_terca INT NULL,
  tempo_quarta INT NULL,
  tempo_quinta INT NULL,
  tempo_sexta INT NULL,
  CONSTRAINT fk_turmas_ano FOREIGN KEY (ano_letivo_id) REFERENCES anos_letivos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS modulos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  turma_id INT NOT NULL,
  nome VARCHAR(255) NOT NULL,
  total_aulas INT NOT NULL,
  tolerancia INT NOT NULL DEFAULT 2,
  INDEX ix_modulos_turma (turma_id),
  CONSTRAINT fk_modulos_turma FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS periodos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(100) NOT NULL,
  tipo VARCHAR(20) NOT NULL DEFAULT 'anual',
  data_inicio DATE NOT NULL,
  data_fim DATE NOT NULL,
  turma_id INT NOT NULL,
  modulo_id INT NULL,
  INDEX ix_periodos_turma (turma_id),
  CONSTRAINT fk_periodos_turma FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE CASCADE,
  CONSTRAINT fk_periodos_modulo FOREIGN KEY (modulo_id) REFERENCES modulos(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS calendario_aulas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  turma_id INT NOT NULL,
  periodo_id INT NOT NULL,
  modulo_id INT NULL,
  data DATE NOT NULL,
  weekday INT NOT NULL,
  numero_modulo INT NULL,
  total_geral INT NULL,
  sumarios VARCHAR(255) NULL,
  tipo VARCHAR(50) NOT NULL DEFAULT 'normal',
  apagado TINYINT(1) NOT NULL DEFAULT 0,
  tempos_sem_aula INT NOT NULL DEFAULT 0,
  observacoes TEXT NULL,
  sumario TEXT NULL,
  previsao TEXT NULL,
  atividade TINYINT(1) NOT NULL DEFAULT 0,
  atividade_nome TEXT NULL,
  INDEX ix_cal_aulas_turma_data (turma_id, data, apagado),
  INDEX ix_cal_aulas_periodo (periodo_id, data),
  INDEX ix_cal_aulas_modulo (modulo_id),
  CONSTRAINT fk_cal_turma FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE CASCADE,
  CONSTRAINT fk_cal_periodo FOREIGN KEY (periodo_id) REFERENCES periodos(id) ON DELETE CASCADE,
  CONSTRAINT fk_cal_modulo FOREIGN KEY (modulo_id) REFERENCES modulos(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schema_version(version) VALUES ('001_init');
