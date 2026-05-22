-- Append-only log of one row per GitHub Actions agent workflow run.
-- Each agent workflow (dev-agent, qa-code bug007-gate, post-deploy
-- smoke + agent-qa, migration-executor apply + finalize, bug-triage,
-- pm-agent) appends a row via the HMAC /agent-ops/report-run endpoint
-- after the agent step finishes. Read by GET /admin/agent-activity
-- for the 14-day cost + activity rollup. Mirrors the llm_usage
-- pattern (idx_<table>_ts).
--
-- NOT BUG-007 class: only the /admin/agent-activity (read) and
-- /agent-ops/report-run (write) endpoints touch this table. If the
-- table is missing, /admin/agent-activity returns an empty rollup and
-- /agent-ops/report-run returns 500 — neither path is hit on user
-- traffic.
CREATE TABLE IF NOT EXISTS agent_runs (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  workflow         VARCHAR(64) NOT NULL,
  job              VARCHAR(64) NOT NULL DEFAULT '',
  run_id           BIGINT UNSIGNED NOT NULL DEFAULT 0,
  conclusion       VARCHAR(32) NOT NULL DEFAULT '',
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  est_cost_usd     DECIMAL(10,5) NOT NULL DEFAULT 0,
  pr_number        INT UNSIGNED NOT NULL DEFAULT 0,
  notes            VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  KEY idx_agent_runs_ts (ts),
  KEY idx_agent_runs_workflow_ts (workflow, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
