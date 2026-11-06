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
  level  INTEGER,                   -- (an existing database gets them from migrate_001_stats.sql)
  device TEXT,                      -- windows/mac/linux/android/other, shown on the board, and the Re:Cast version,
  version TEXT                      -- not shown; sent by newer clients (migrate_003_device_feedback.sql)
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

-- The public feedback board on the website (feedback.js). A post is what the poster typed: a kind
-- (review, idea, bug...), an optional nickname, device and version, the message, and an optional
-- email address that is never shown or sent anywhere except to the project's own inbox, so the owner
-- can answer. The owner's public reply, and whether a reported bug is fixed, are kept with it.
-- (An existing database gets these from migrate_003_device_feedback.sql.)
CREATE TABLE IF NOT EXISTS feedback (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  posted  INTEGER NOT NULL,          -- unix seconds
  kind    TEXT    NOT NULL,          -- one of feedback.js KINDS
  nick    TEXT,                      -- shown; empty shows as "A player"
  device  TEXT,                      -- one of feedback.js DEVICES, shown
  version TEXT,                      -- shown
  message TEXT    NOT NULL,          -- shown
  email   TEXT,                      -- private: never shown, only in the email to the owner
  hidden  INTEGER NOT NULL DEFAULT 0,
  fixed   INTEGER NOT NULL DEFAULT 0,
  reply   TEXT,                      -- the owner's public answer
  replied INTEGER                    -- unix seconds of that answer
);
CREATE INDEX IF NOT EXISTS feedback_list ON feedback (hidden, id);
-- Posting is limited per address with the same salted, shortened hash as scores, kept an hour.
CREATE TABLE IF NOT EXISTS feedback_recent (
  k    TEXT    NOT NULL,
  seen INTEGER NOT NULL
);
