-- Keywords live only on algorithms now (drops /terms surface).
--
-- Three things in order:
--   1. Copy existing per-user keywords (`user_term_prefs`) into each
--      user's currently-active `algorithm_term_prefs` row so users
--      don't lose what they had on the deprecated /terms page.
--      INSERT IGNORE keeps a pre-existing per-algo term in place if it
--      collides on (algorithm_id, term).
--   2. Add a `keywords_json` snapshot column to `shared_algorithms` so
--      gallery publish carries the algorithm's keywords and adopt can
--      clone them into the new profile. Added as nullable to handle
--      existing rows under strict mode, backfilled to '[]', then
--      tightened to NOT NULL — TEXT columns under MySQL strict mode
--      reject an unqualified ADD COLUMN NOT NULL on a populated table.
--   3. Drop the now-unused `user_term_prefs` table.
--
-- Load-bearing (BUG-007 class): the merged code DROPs the
-- `user_term_prefs` query in routes/feed.py and SELECTs `keywords_json`
-- in routes/gallery.adopt(); a missing column / lingering table both
-- cleanly resolve once this is applied + the Python App is restarted.

INSERT IGNORE INTO algorithm_term_prefs (algorithm_id, term, mode, weight)
SELECT ua.id, utp.term, utp.mode, utp.weight
FROM user_term_prefs utp
JOIN user_algorithms ua
  ON ua.user_id = utp.user_id
 AND ua.is_active = 1;

ALTER TABLE shared_algorithms
  ADD COLUMN keywords_json TEXT NULL AFTER weights_json;

UPDATE shared_algorithms SET keywords_json = '[]' WHERE keywords_json IS NULL;

ALTER TABLE shared_algorithms
  MODIFY COLUMN keywords_json TEXT NOT NULL;

DROP TABLE user_term_prefs;
