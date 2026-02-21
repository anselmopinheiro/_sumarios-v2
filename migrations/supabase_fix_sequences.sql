-- Supabase/Postgres sequence repair for public schema.
-- Run in Supabase SQL Editor when duplicate-key on PK(id) appears after imports/migrations.

BEGIN;

-- 1) Ensure aulas_alunos.id has sequence/default if missing.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'aulas_alunos'
      AND column_name = 'id'
      AND column_default IS NULL
  ) THEN
    CREATE SEQUENCE IF NOT EXISTS public.aulas_alunos_id_seq;
    ALTER TABLE public.aulas_alunos
      ALTER COLUMN id SET DEFAULT nextval('public.aulas_alunos_id_seq');
    ALTER SEQUENCE public.aulas_alunos_id_seq OWNED BY public.aulas_alunos.id;
  END IF;
END $$;

-- 2) Align all sequences for public tables that have an id column.
DO $$
DECLARE
  r RECORD;
  v_seq_name text;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND column_name = 'id'
  LOOP
    v_seq_name := pg_get_serial_sequence(format('%I.%I', r.table_schema, r.table_name), 'id');

    IF v_seq_name IS NULL THEN
      v_seq_name := format('%I.%I_id_seq', r.table_schema, r.table_name);
      EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %s', v_seq_name);
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN id SET DEFAULT nextval(%L)',
        r.table_schema,
        r.table_name,
        v_seq_name
      );
      EXECUTE format('ALTER SEQUENCE %s OWNED BY %I.%I.id', v_seq_name, r.table_schema, r.table_name);
    END IF;

    EXECUTE format(
      'SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I.%I), 1), true)',
      v_seq_name,
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;

COMMIT;
