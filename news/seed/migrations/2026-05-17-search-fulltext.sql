-- Full-text search across articles (roadmap "Search across articles").
-- Adds an InnoDB FULLTEXT index over the columns the /search route MATCHes.
-- MySQL 5.7+ / InnoDB. Safe to re-run guarded: skip if ft_articles_search
-- already exists (ADD FULLTEXT errors on a duplicate index name).

ALTER TABLE articles
  ADD FULLTEXT INDEX ft_articles_search (title, summary);
