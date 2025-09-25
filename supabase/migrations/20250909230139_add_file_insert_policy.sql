create policy "Users can create files."
on "public"."files"
as permissive
for insert
to authenticated
with check ((( SELECT auth.uid() AS uid) = user_id));



