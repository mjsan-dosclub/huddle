CREATE TABLE customer_password_resets(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),created INTEGER NOT NULL,expires INTEGER NOT NULL,used INTEGER);
CREATE INDEX customer_password_resets_account ON customer_password_resets(account_id);
INSERT INTO schema_migrations VALUES(10,CAST(strftime('%s','now') AS INTEGER));
