insert into storage.buckets (id, name)
values ('files', 'files');


-- Policy: Allow authenticated uploads into user-specific folders
create policy "Allow authenticated uploads"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'files'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
  );

-- Policy: Allow users to retrieve files where they are owner
create policy "Individual user Access"
  on storage.objects
  for select
  to authenticated
  using (
    (select auth.uid()) = owner_id::uuid
  );
