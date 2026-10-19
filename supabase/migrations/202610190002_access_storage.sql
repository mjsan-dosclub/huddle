-- Dedicated API credential: set its password using scripts/set_db_password.py.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='huddle_backend') THEN
  CREATE ROLE huddle_backend LOGIN NOINHERIT;
 END IF;
END $$;
GRANT USAGE ON SCHEMA huddle TO huddle_backend;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA huddle TO huddle_backend;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA huddle TO huddle_backend;
REVOKE ALL ON SCHEMA huddle FROM PUBLIC;
DO $$ DECLARE t TEXT; r TEXT; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='huddle' LOOP
  EXECUTE format('ALTER TABLE huddle.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON huddle.%I FROM PUBLIC',t);
  EXECUTE format('CREATE POLICY backend_only ON huddle.%I TO huddle_backend USING (TRUE) WITH CHECK (TRUE)',t);
 END LOOP;
 FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON SCHEMA huddle FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA huddle FROM %I',r);
  END IF;
 END LOOP;
 -- Storage is Supabase-specific; generic PostgreSQL tests have no storage schema.
 IF to_regclass('storage.buckets') IS NOT NULL THEN
  INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
   VALUES('huddle-assets','huddle-assets',FALSE,3145728,ARRAY['image/png'])
   ON CONFLICT(id) DO UPDATE SET public=FALSE,file_size_limit=3145728,allowed_mime_types=ARRAY['image/png'];
 END IF;
END $$;
-- No browser storage policies: service-role storage requests originate in the API.
-- The backend role is trusted; API session/RBAC and tenant predicates isolate members.
