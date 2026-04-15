-- Migration v2: HA + waiting video support
-- Run once on existing databases (safe to run multiple times due to IF NOT EXISTS)
ALTER TABLE settings ADD COLUMN IF NOT EXISTS waiting_video_url VARCHAR(500);
