-- Garantir coluna trabalhos.data_limite em Postgres/Supabase
ALTER TABLE IF EXISTS trabalhos
  ADD COLUMN IF NOT EXISTS data_limite TIMESTAMP NULL;
