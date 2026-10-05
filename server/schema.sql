-- Shared leaderboard storage. Anonymous by design: a row says what was scored on
-- which level, never by whom.
CREATE TABLE IF NOT EXISTS scores (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  posted INTEGER NOT NULL,          -- unix seconds, for pruning and stats
  aid    TEXT    NOT NULL,          -- the game's app id, always "KH"
  lid    TEXT    NOT NULL,          -- world: training/island/wonderland/agrabah/castle
  score  INTEGER NOT NULL,          -- Munny + (100 x EXP), as the game computes it
  secs   INTEGER,                   -- how long the run took, or NULL
  munny  INTEGER,                   -- the Munny, EXP and level behind the score, read from the
  exp    INTEGER,                   -- game's Summary screen; NULL for scores from older clients
  level  INTEGER                    -- (an existing database gets them from migrate_001_stats.sql)
);
CREATE INDEX IF NOT EXISTS scores_lid ON scores (lid, score);

-- Rate limiting only: a salted, truncated hash of the posting address, deleted
-- after ten minutes. Nothing here can be turned back into an IP or a person.
CREATE TABLE IF NOT EXISTS recent (
  k    TEXT    NOT NULL,
  seen INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS recent_k ON recent (k, seen);

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
