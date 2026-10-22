-- Drop the seeded "CabinetNow.com" quote footer (owner 2026-10-22: no
-- CabinetNow text in the product). Only the untouched seed value is cleared;
-- a footer an admin wrote stays.
UPDATE org_settings
SET quote_footer_md = ''
WHERE quote_footer_md = 'CabinetNow.com — custom cabinet products, shipped nationwide.';
