-- Migration: Add raw_markdown column to files table
-- This migration adds support for storing the original markdown extracted from PDFs
-- before it is cleaned for TTS processing

-- Add raw_markdown column to store original markdown before TTS cleaning
ALTER TABLE files
ADD COLUMN raw_markdown TEXT;

-- Add comment to clarify the difference between raw_markdown and parsed_text
COMMENT ON COLUMN files.raw_markdown IS 'Original markdown extracted from PDF with formatting preserved. Stored before TTS cleaning.';
COMMENT ON COLUMN files.parsed_text IS 'Cleaned text suitable for TTS, with markdown formatting removed. Derived from raw_markdown.';
