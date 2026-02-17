-- Alinha sequences em tabelas BASE TABLE do schema public com coluna id.
DO $$
DECLARE
  r RECORD;
  seq_name text;
BEGIN
  FOR r IN
    SELECT c.table_schema, c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema
     AND t.table_name = c.table_name
    WHERE c.table_schema = 'public'
      AND c.column_name = 'id'
      AND t.table_type = 'BASE TABLE'
    ORDER BY c.table_name
  LOOP
    seq_name := pg_get_serial_sequence(format('%I.%I', r.table_schema, r.table_name), 'id');

    IF seq_name IS NOT NULL THEN
      EXECUTE format(
        'SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I.%I), 1), true)',
        seq_name,
        r.table_schema,
        r.table_name
      );
      RAISE NOTICE 'FIX SEQ OK | table=%.% | sequence=%', r.table_schema, r.table_name, seq_name;
    END IF;
  END LOOP;
END $$;
