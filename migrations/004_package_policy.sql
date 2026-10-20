-- Seed configurable organization ownership limits once; future changes belong to the package manager.
UPDATE plans SET entitlements=json_set(entitlements,'$.max_owned_organizations',CASE id WHEN 'free' THEN 2 WHEN 'pro' THEN 5 WHEN 'enterprise' THEN 20 END) WHERE id IN ('free','pro','enterprise') AND json_type(entitlements,'$.max_owned_organizations') IS NULL;
INSERT INTO schema_migrations VALUES(4,CAST(strftime('%s','now') AS INTEGER));
