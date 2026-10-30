-- 0016_portals.sql — 0.28.0: the tenant's portal (backend/lessee.py). One login per tenant file; the tenant's own acknowledgement of the privacy notice.
ALTER TABLE users ADD COLUMN IF NOT EXISTS lessee_id bigint;
ALTER TABLE users ADD CONSTRAINT fk_users_lessee FOREIGN KEY (lessee_id) REFERENCES tenants_l(id);
CREATE UNIQUE INDEX ux_users_lessee ON users(org_id, lessee_id) WHERE lessee_id IS NOT NULL;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS consent_at text;
ALTER TABLE tenants_l ADD COLUMN IF NOT EXISTS consent_version text;
