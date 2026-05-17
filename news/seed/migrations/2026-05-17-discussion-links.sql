-- Discussion links (Techmeme-style): store the Reddit/HN thread permalink and
-- subreddit alongside the popularity signal we already collect, so the feed
-- card and story dossier can link out to the conversation.
-- Existing rows get NULL permalink and simply don't render a discussion line
-- until popularity_poll refreshes them on its next 30-min tick.

ALTER TABLE popularity_signals
  ADD COLUMN permalink VARCHAR(1024) DEFAULT NULL AFTER comments,
  ADD COLUMN subreddit  VARCHAR(64) DEFAULT NULL AFTER permalink;
