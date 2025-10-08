insert into storage.buckets (id, name)
values ('files', 'files');


-- Policy: Allow authenticated uploads into user-specific folders (if enabled)
create policy "Allow authenticated uploads"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'files'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
    and EXISTS (
      SELECT 1 FROM user_profiles
      WHERE user_profiles.user_id = (select auth.uid())
      AND user_profiles.enabled = true
    )
  );

-- Policy: Allow users to retrieve files where they are owner (if enabled)
create policy "Individual user Access"
  on storage.objects
  for select
  to authenticated
  using (
    (select auth.uid()) = owner_id::uuid
    and EXISTS (
      SELECT 1 FROM user_profiles
      WHERE user_profiles.user_id = (select auth.uid())
      AND user_profiles.enabled = true
    )
  );

-- Policy: Allow users to update their own files (if enabled)
create policy "Allow users to update their own files"
  on storage.objects
  for update
  to authenticated
  using (
    (select auth.uid()) = owner_id::uuid
    and EXISTS (
      SELECT 1 FROM user_profiles
      WHERE user_profiles.user_id = (select auth.uid())
      AND user_profiles.enabled = true
    )
  )
  with check (
    bucket_id = 'files'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
    and EXISTS (
      SELECT 1 FROM user_profiles
      WHERE user_profiles.user_id = (select auth.uid())
      AND user_profiles.enabled = true
    )
  );

-- Policy: Allow users to delete their own files (if enabled)
create policy "Allow users to delete their own files"
  on storage.objects
  for delete
  to authenticated
  using (
    (select auth.uid()) = owner_id::uuid
    and EXISTS (
      SELECT 1 FROM user_profiles
      WHERE user_profiles.user_id = (select auth.uid())
      AND user_profiles.enabled = true
    )
  );
