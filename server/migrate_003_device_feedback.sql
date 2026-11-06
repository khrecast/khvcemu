-- Adds where a score came from, and the website's feedback board. Run ONCE against the live database (from server/):
--
--   npx wrangler d1 execute khvcemu-leaderboard --remote --file migrate_003_device_feedback.sql
--
-- It adds two empty columns to scores (no score is changed; older rows keep NULL there) and creates the two
-- feedback tables. The ALTER lines fail if run a second time ("duplicate column"); the tables are IF NOT EXISTS.
-- The worker works before and after it, so the order of this and `npx wrangler deploy` does not matter, but
-- the feedback board only stores posts once the tables exist.
ALTER TABLE scores ADD COLUMN device TEXT;
ALTER TABLE scores ADD COLUMN version TEXT;

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
