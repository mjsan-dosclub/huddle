SET LOCAL search_path TO huddle, pg_catalog;
CREATE TABLE sales_staff_credentials(account_id TEXT PRIMARY KEY REFERENCES accounts(id),name TEXT NOT NULL,password_hash TEXT NOT NULL,must_change INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL,updated INTEGER NOT NULL);
CREATE TABLE sales_staff_sessions(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES sales_staff_credentials(account_id),credential_version INTEGER NOT NULL,expires INTEGER NOT NULL);
CREATE INDEX sales_staff_session_account ON sales_staff_sessions(account_id);
INSERT INTO schema_migrations VALUES(9,CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT));

ALTER TABLE sales_staff_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales_staff_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sales_staff_credentials,sales_staff_sessions FROM PUBLIC;
CREATE POLICY backend_only ON sales_staff_credentials TO huddle_backend USING(TRUE) WITH CHECK(TRUE);
CREATE POLICY backend_only ON sales_staff_sessions TO huddle_backend USING(TRUE) WITH CHECK(TRUE);
GRANT SELECT,INSERT ON sales_staff_credentials,sales_staff_sessions TO huddle_backend;
GRANT UPDATE(name,password_hash,must_change,version,updated) ON sales_staff_credentials TO huddle_backend;
GRANT DELETE ON sales_staff_sessions TO huddle_backend;
