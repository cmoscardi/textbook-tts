CREATE TABLE files (
    file_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    file_name   VARCHAR(512) NOT NULL,
    file_path   TEXT NOT NULL,   -- local path or S3 URL
    file_size   BIGINT NOT NULL, -- in bytes
    mime_type   VARCHAR(255),
    checksum    CHAR(64),        -- SHA-256 hex
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

alter table files enable row level security;

create policy "Users can create files."
on files
for insert
to authenticated                -- the Postgres Role (recommended)
with check (
  (select auth.uid()) = user_id -- the actual Policy
);


create policy "Users can see their own files only."
on files
for select
using ( (select auth.uid()) = user_id );
