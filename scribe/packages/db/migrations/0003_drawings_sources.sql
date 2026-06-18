-- Crawl drawings-bearing solicitations only. Permit datasets (Socrata) carry
-- no drawings, so pause them without deleting — re-enableable from Admin. Keep
-- SAM.gov active (federal solicitations attach public plan PDFs) and broaden
-- its casework keywords. See engineering-history 2026-06-18 (c).

UPDATE sources SET status = 'inactive'
 WHERE type = 'socrata'
   AND name IN (
     'San Francisco permits (Socrata)',
     'Los Angeles permits (Socrata)',
     'NYC DOB permits (Socrata)'
   );

UPDATE sources
   SET status = 'active',
       config = jsonb_build_object(
         'keywords', jsonb_build_array(
           'cabinet', 'casework', 'millwork',
           'architectural woodwork', 'kitchen renovation'
         ),
         'jurisdiction', 'Federal'
       )
 WHERE type = 'samgov';
