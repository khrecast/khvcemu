-- Adds the Munny, EXP and level columns to a leaderboard database made before them.
-- Run ONCE against the live database (from server/), then it is done:
--
--   npx wrangler d1 execute khvcemu-leaderboard --remote --file migrate_001_stats.sql
--
-- It only adds empty columns, so no score is changed or lost, and older clients (which do
-- not send these) keep working. Running it a second time fails with "duplicate column name",
-- which is harmless. The worker also works without it, just without storing the numbers, so it
-- does not matter whether this or `npx wrangler deploy` comes first.
ALTER TABLE scores ADD COLUMN munny INTEGER;
ALTER TABLE scores ADD COLUMN exp   INTEGER;
ALTER TABLE scores ADD COLUMN level INTEGER;
