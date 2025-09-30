CREATE TABLE file_conversions (
    conversion_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id         UUID NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,           -- output file path or URL
    job_id          VARCHAR(255) NOT NULL,   -- Celery job ID
    job_completion  INTEGER NOT NULL DEFAULT 0 CHECK (job_completion >= 0 AND job_completion <= 100),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Enable row level security
ALTER TABLE file_conversions ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view conversions for their own files
CREATE POLICY "Users can view conversions for their own files."
ON file_conversions
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM files
        WHERE files.file_id = file_conversions.file_id
        AND files.user_id = (SELECT auth.uid())
    )
);

-- Index for faster lookups
CREATE INDEX idx_file_conversions_file_id ON file_conversions(file_id);
CREATE INDEX idx_file_conversions_job_id ON file_conversions(job_id);
CREATE INDEX idx_file_conversions_status ON file_conversions(status);

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_file_conversions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at on row updates
CREATE TRIGGER trigger_update_file_conversions_updated_at
    BEFORE UPDATE ON file_conversions
    FOR EACH ROW
    EXECUTE FUNCTION update_file_conversions_updated_at();