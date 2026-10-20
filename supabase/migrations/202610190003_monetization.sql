SET LOCAL search_path TO huddle, pg_catalog;
-- Additive monetization schema. Never grants platform access to tenant Owners.
CREATE TABLE platform_admin_grants(account_id TEXT PRIMARY KEY REFERENCES accounts(id),created INTEGER NOT NULL,granted_by TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE platform_security(account_id TEXT PRIMARY KEY REFERENCES accounts(id),secret TEXT,pending_secret TEXT,enabled INTEGER NOT NULL DEFAULT 0,last_counter INTEGER NOT NULL DEFAULT -1);
CREATE TABLE platform_sessions(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),expires INTEGER NOT NULL);
CREATE TABLE plans(id TEXT PRIMARY KEY,name TEXT NOT NULL,version INTEGER NOT NULL,entitlements TEXT NOT NULL);
CREATE TABLE plan_prices(id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES plans(id),interval TEXT NOT NULL CHECK(interval IN ('monthly','annual')),amount_paise INTEGER NOT NULL CHECK(amount_paise>=0),currency TEXT NOT NULL CHECK(currency='INR'),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE subscriptions(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES organizations(id),plan_id TEXT NOT NULL REFERENCES plans(id),price_id TEXT REFERENCES plan_prices(id),status TEXT NOT NULL CHECK(status IN ('FREE','AUTHENTICATED','TRIALING','ACTIVE','PAST_DUE','CANCELED','HALTED','PAUSED','COMPLETED')),mode TEXT NOT NULL CHECK(mode IN ('none','test','live','offline')),provider_subscription_id TEXT UNIQUE,provider_customer_id TEXT,current_period_end INTEGER NOT NULL DEFAULT 0,grace_until INTEGER NOT NULL DEFAULT 0,last_event_at INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(tenant_id,id));
CREATE INDEX subscription_tenant ON subscriptions(tenant_id,created);
CREATE TABLE entitlement_overrides(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES organizations(id),plan_id TEXT NOT NULL REFERENCES plans(id),limits TEXT NOT NULL DEFAULT '{}',reason TEXT NOT NULL,created_by TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL,revoked_at INTEGER);
CREATE INDEX override_tenant ON entitlement_overrides(tenant_id,expires);
CREATE TABLE billing_events(id TEXT PRIMARY KEY,mode TEXT NOT NULL,provider_event_id TEXT NOT NULL,payload_hash TEXT NOT NULL,event_type TEXT NOT NULL,tenant_id TEXT REFERENCES organizations(id),provider_subscription_id TEXT,occurred INTEGER NOT NULL,received INTEGER NOT NULL,outcome TEXT NOT NULL,UNIQUE(mode,provider_event_id));
CREATE TABLE payments(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES organizations(id),subscription_id TEXT NOT NULL,mode TEXT NOT NULL,provider_payment_id TEXT NOT NULL,amount_paise INTEGER NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,paid_at INTEGER NOT NULL,reference TEXT NOT NULL DEFAULT '',UNIQUE(mode,provider_payment_id),FOREIGN KEY(tenant_id,subscription_id) REFERENCES subscriptions(tenant_id,id));
CREATE TABLE billing_notices(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES organizations(id),kind TEXT NOT NULL,message TEXT NOT NULL,created INTEGER NOT NULL,resolved INTEGER);
CREATE TABLE platform_audit(id TEXT PRIMARY KEY,actor_account_id TEXT NOT NULL,tenant_id TEXT REFERENCES organizations(id),action TEXT NOT NULL,reason TEXT NOT NULL,details TEXT NOT NULL,created INTEGER NOT NULL);
CREATE TABLE support_sessions(id TEXT PRIMARY KEY,actor_account_id TEXT NOT NULL REFERENCES accounts(id),tenant_id TEXT NOT NULL REFERENCES organizations(id),reason TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL,ended INTEGER);
INSERT INTO plans VALUES('free','Free',1,'{"max_cards": 1, "max_seats": 1, "max_admins": 1, "custom_branding": false, "custom_qr": false, "remove_branding": false, "lead_capture": false, "lead_export": false, "bulk_import": false, "wallet": false}');
INSERT INTO plans VALUES('pro','Pro',1,'{"max_cards": 10, "max_seats": 10, "max_admins": 10, "custom_branding": true, "custom_qr": true, "remove_branding": false, "lead_capture": true, "lead_export": true, "bulk_import": true, "wallet": true}');
INSERT INTO plans VALUES('enterprise','Enterprise',1,'{"max_cards": null, "max_seats": null, "max_admins": null, "custom_branding": true, "custom_qr": true, "remove_branding": true, "lead_capture": true, "lead_export": true, "bulk_import": true, "wallet": true}');
INSERT INTO plan_prices VALUES('pro-monthly','pro','monthly',49900,'INR',1);
INSERT INTO plan_prices VALUES('pro-annual','pro','annual',499900,'INR',1);
INSERT INTO plan_prices VALUES('enterprise-monthly','enterprise','monthly',249900,'INR',1);
INSERT INTO subscriptions(id,tenant_id,plan_id,status,mode,created,updated) SELECT 'migration-sub-'||id,id,'free','FREE','none',CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT),CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT) FROM organizations;
INSERT INTO entitlement_overrides(id,tenant_id,plan_id,reason,created_by,created,expires) SELECT 'migration-grant-'||id,id,'enterprise','90-day compatibility grant for pre-billing organizations','migration',CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT),CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT)+7776000 FROM organizations;
INSERT INTO platform_audit SELECT 'migration-audit-'||id,'migration',id,'tenant.compatibility_grant','90-day pre-billing compatibility grant','{"plan":"enterprise","days":90}',CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT) FROM organizations;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['platform_admin_grants','platform_security','platform_sessions','plans','plan_prices','subscriptions','entitlement_overrides','billing_events','payments','billing_notices','platform_audit','support_sessions'] LOOP
  EXECUTE format('ALTER TABLE huddle.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON huddle.%I FROM PUBLIC',t);
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN EXECUTE format('REVOKE ALL ON huddle.%I FROM anon',t); END IF;
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN EXECUTE format('REVOKE ALL ON huddle.%I FROM authenticated',t); END IF;
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON huddle.%I TO huddle_backend',t);
  EXECUTE format('CREATE POLICY backend_only ON huddle.%I TO huddle_backend USING (TRUE) WITH CHECK (TRUE)',t);
 END LOOP;
END $$;
-- Platform grants are provisioned by an offline migration administrator only.
REVOKE INSERT,UPDATE,DELETE ON platform_admin_grants,plans FROM huddle_backend;
REVOKE UPDATE,DELETE ON plan_prices FROM huddle_backend;
GRANT UPDATE(active) ON plan_prices TO huddle_backend;
REVOKE UPDATE,DELETE ON platform_audit FROM huddle_backend;
INSERT INTO schema_migrations VALUES(3,CAST(EXTRACT(EPOCH FROM NOW()) AS BIGINT));
