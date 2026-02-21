-- Fix para Supabase/Postgres: garantir auto-increment e sequence alinhada
-- Tabela alvo: public.sumario_historico

BEGIN;

-- Garantir PK em id (se faltar)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname = 'sumario_historico'
      AND c.contype = 'p'
  ) THEN
    ALTER TABLE public.sumario_historico
      ADD CONSTRAINT sumario_historico_pkey PRIMARY KEY (id);
  END IF;
END $$;

-- Garantir default em id via sequence (compatível com serial/identity)
DO $$
DECLARE
  seq_name text;
BEGIN
  seq_name := pg_get_serial_sequence('public.sumario_historico', 'id');

  IF seq_name IS NULL THEN
    CREATE SEQUENCE IF NOT EXISTS public.sumario_historico_id_seq;
    ALTER TABLE public.sumario_historico
      ALTER COLUMN id SET DEFAULT nextval('public.sumario_historico_id_seq');
    ALTER SEQUENCE public.sumario_historico_id_seq
      OWNED BY public.sumario_historico.id;
    seq_name := 'public.sumario_historico_id_seq';
  END IF;

  EXECUTE format(
    'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM public.sumario_historico), true)',
    seq_name
  );
END $$;

COMMIT;
