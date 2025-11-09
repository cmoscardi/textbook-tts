-- Migration: Split parsing and conversion tracking
-- This migration adds support for separate /parse and /convert endpoints

-- Add parsed text storage to files table
ALTER TABLE files
ADD COLUMN parsed_text TEXT,
ADD COLUMN parsed_at TIMESTAMP;

CREATE INDEX idx_files_parsed_at ON files(parsed_at) WHERE parsed_text IS NOT NULL;

-- Create file_parsings table to track PDF parsing jobs
CREATE TABLE file_parsings (
    parsing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES files(file_id) ON DELETE CASCADE UNIQUE,
    job_id VARCHAR(255) NOT NULL UNIQUE,
    job_completion INTEGER NOT NULL DEFAULT 0 CHECK (job_completion >= 0 AND job_completion <= 100),
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_file_parsings_file_id ON file_parsings(file_id);
CREATE INDEX idx_file_parsings_job_id ON file_parsings(job_id);
CREATE INDEX idx_file_parsings_status ON file_parsings(status);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_file_parsings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER file_parsings_updated_at
    BEFORE UPDATE ON file_parsings
    FOR EACH ROW
    EXECUTE FUNCTION update_file_parsings_updated_at();

-- Update file_conversions to add error tracking (keeping existing structure for now)
ALTER TABLE file_conversions
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Add comment to clarify that file_conversions now only tracks TTS conversion
COMMENT ON TABLE file_conversions IS 'Tracks text-to-speech conversion jobs. Parsing is tracked separately in file_parsings.';
COMMENT ON TABLE file_parsings IS 'Tracks PDF parsing jobs. Must be completed before conversion.';
COMMENT ON COLUMN files.parsed_text IS 'Extracted text from PDF parsing. Populated by /parse endpoint.';
