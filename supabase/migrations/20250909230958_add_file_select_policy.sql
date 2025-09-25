create policy "Users can see their own files only."
on "public"."files"
as permissive
for select
to public
using ((( SELECT auth.uid() AS uid) = user_id));



