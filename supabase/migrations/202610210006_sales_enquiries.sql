SET LOCAL search_path TO huddle, pg_catalog;
ALTER TABLE enterprise_quote_requests ADD COLUMN details TEXT NOT NULL DEFAULT '{}';
INSERT INTO schema_migrations VALUES(6,CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT));
