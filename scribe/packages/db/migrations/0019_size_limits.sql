-- Admin-set size limits per product (Admin › Pricing, owner 2026-10-20).
-- Empty = no limit. The seed's dim_bounds column stays but is not enforced.
ALTER TABLE product_lines
  ADD COLUMN IF NOT EXISTS size_limits jsonb NOT NULL DEFAULT '{}'::jsonb;
