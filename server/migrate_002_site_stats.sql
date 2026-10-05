-- Adds the anonymous website counters (see schema.sql). Run ONCE against the live database (from server/):
--
--   npx wrangler d1 execute khvcemu-leaderboard --remote --file migrate_002_site_stats.sql
--
-- It only creates one new, empty table, so no score is touched. It is safe to run twice (IF NOT EXISTS), and
-- the worker answers the website's counters even before it exists (it just does not store them), so the
-- order of this and `npx wrangler deploy` does not matter.
-- Anonymous website counters: how many times each page was opened and each button clicked, per
-- day. A row is (UTC day, event name, count): no address, no cookie, no browser details, nothing
-- that can be tied to a person. Only the names listed in worker.js SITE_EVENTS are ever counted.
-- (An existing database gets it from migrate_002_site_stats.sql.)
CREATE TABLE IF NOT EXISTS site_stats (
  day  TEXT    NOT NULL,            -- YYYY-MM-DD, UTC
  name TEXT    NOT NULL,            -- view:home, dl:win64, ...
  n    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, name)
);
