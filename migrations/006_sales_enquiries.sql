-- Add structured sales requirements without changing existing quote records.
ALTER TABLE enterprise_quote_requests ADD COLUMN details TEXT NOT NULL DEFAULT '{}';
INSERT INTO schema_migrations VALUES(6,CAST(strftime('%s','now') AS INTEGER));
