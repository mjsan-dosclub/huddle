SET LOCAL search_path TO huddle, pg_catalog;
-- One-time defaults. Runtime limits come exclusively from the plans catalogue.
UPDATE plans SET entitlements=(entitlements::jsonb || jsonb_build_object('max_owned_organizations',CASE id WHEN 'free' THEN 2 WHEN 'pro' THEN 5 WHEN 'enterprise' THEN 20 END))::text WHERE id IN ('free','pro','enterprise') AND NOT entitlements::jsonb ? 'max_owned_organizations';
-- The existing backend may update package definitions through the authenticated operator API.
-- It cannot insert/delete plans or change their IDs. Platform grants remain offline-only.
GRANT UPDATE(name,version,entitlements) ON plans TO huddle_backend;
INSERT INTO schema_migrations VALUES(4,CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT));
