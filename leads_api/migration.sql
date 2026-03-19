-- Run this once in your Supabase SQL Editor

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS "google map leads" (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    business_name    TEXT,
    phone            TEXT,
    address          TEXT,
    rating           TEXT,
    website          TEXT,
    maps_url         TEXT,
    keyword          TEXT,

    emails           TEXT[]  NOT NULL DEFAULT '{}',
    firecrawl_emails TEXT[]  NOT NULL DEFAULT '{}',
    socials          JSONB   NOT NULL DEFAULT '{}'::jsonb,
    business_summary TEXT,

    CONSTRAINT uq_business_keyword UNIQUE (business_name, keyword)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_gml_keyword     ON "google map leads" (keyword);
CREATE INDEX IF NOT EXISTS idx_gml_created_at  ON "google map leads" (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gml_emails      ON "google map leads" USING GIN (emails);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_updated_at ON "google map leads";
CREATE TRIGGER trg_updated_at
    BEFORE UPDATE ON "google map leads"
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();

-- RLS: only service-role key can read/write
ALTER TABLE "google map leads" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON "google map leads"
    FOR ALL TO service_role USING (true) WITH CHECK (true);

SELECT 'Migration done ✅' AS status;