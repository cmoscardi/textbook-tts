-- Migration: Add timing fields to file_parsings

ALTER TABLE file_parsings
ADD COLUMN total_time NUMERIC,
ADD COLUMN time_to_first_page NUMERIC;

COMMENT ON COLUMN file_parsings.total_time IS 'Total parse duration in seconds (download + OCR + DB writes)';
COMMENT ON COLUMN file_parsings.time_to_first_page IS 'Seconds from task start until the first page is saved to the database';
