-- Garantir tipos DATE em Postgres/Supabase para o módulo Trabalhos
ALTER TABLE IF EXISTS public.trabalhos
  ADD COLUMN IF NOT EXISTS data_limite DATE NULL;

ALTER TABLE IF EXISTS public.entregas
  ADD COLUMN IF NOT EXISTS data_entrega DATE NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'trabalhos'
      AND column_name = 'data_limite'
      AND data_type <> 'date'
  ) THEN
    ALTER TABLE public.trabalhos
      ALTER COLUMN data_limite TYPE date
      USING (data_limite::date);
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'entregas'
      AND column_name = 'data_entrega'
      AND data_type <> 'date'
  ) THEN
    ALTER TABLE public.entregas
      ALTER COLUMN data_entrega TYPE date
      USING (data_entrega::date);
  END IF;
END $$;
