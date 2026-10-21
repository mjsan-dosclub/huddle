CREATE TABLE sales_staff_credentials(account_id TEXT PRIMARY KEY REFERENCES accounts(id),name TEXT NOT NULL,password_hash TEXT NOT NULL,must_change INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL,updated INTEGER NOT NULL);
CREATE TABLE sales_staff_sessions(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES sales_staff_credentials(account_id),credential_version INTEGER NOT NULL,expires INTEGER NOT NULL);
CREATE INDEX sales_staff_session_account ON sales_staff_sessions(account_id);
INSERT INTO schema_migrations VALUES(9,CAST(strftime('%s','now') AS INTEGER));
