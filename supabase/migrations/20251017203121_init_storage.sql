insert into storage.buckets (id, name)
values ('files', 'files');

create policy "Allow authenticated uploads"
on "storage"."objects"
as permissive
for insert
to authenticated
with check (((bucket_id = 'files'::text) AND ((storage.foldername(name))[1] = ( SELECT (auth.uid())::text AS uid)) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Allow users to delete their own files"
on "storage"."objects"
as permissive
for delete
to authenticated
using (((( SELECT auth.uid() AS uid) = (owner_id)::uuid) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Allow users to update their own files"
on "storage"."objects"
as permissive
for update
to authenticated
using (((( SELECT auth.uid() AS uid) = (owner_id)::uuid) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))))
with check (((bucket_id = 'files'::text) AND ((storage.foldername(name))[1] = ( SELECT (auth.uid())::text AS uid)) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Individual user Access"
on "storage"."objects"
as permissive
for select
to authenticated
using (((( SELECT auth.uid() AS uid) = (owner_id)::uuid) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));
