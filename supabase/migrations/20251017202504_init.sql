create table "public"."file_conversions" (
    "conversion_id" uuid not null default gen_random_uuid(),
    "file_id" uuid not null,
    "file_path" text not null,
    "job_id" character varying(255) not null,
    "job_completion" integer not null default 0,
    "status" character varying(50) not null default 'pending'::character varying,
    "created_at" timestamp without time zone not null default now(),
    "updated_at" timestamp without time zone not null default now()
);


alter table "public"."file_conversions" enable row level security;

create table "public"."files" (
    "file_id" uuid not null default gen_random_uuid(),
    "user_id" uuid not null,
    "file_name" character varying(512) not null,
    "file_path" text not null,
    "file_size" bigint not null,
    "mime_type" character varying(255),
    "checksum" character(64),
    "uploaded_at" timestamp without time zone not null default now()
);


alter table "public"."files" enable row level security;

create table "public"."user_profiles" (
    "profile_id" uuid not null default gen_random_uuid(),
    "user_id" uuid not null,
    "enabled" boolean not null default false,
    "created_at" timestamp without time zone not null default now(),
    "updated_at" timestamp without time zone not null default now()
);


alter table "public"."user_profiles" enable row level security;

CREATE UNIQUE INDEX file_conversions_pkey ON public.file_conversions USING btree (conversion_id);

CREATE UNIQUE INDEX files_pkey ON public.files USING btree (file_id);

CREATE INDEX idx_file_conversions_file_id ON public.file_conversions USING btree (file_id);

CREATE INDEX idx_file_conversions_job_id ON public.file_conversions USING btree (job_id);

CREATE INDEX idx_file_conversions_status ON public.file_conversions USING btree (status);

CREATE INDEX idx_user_profiles_enabled ON public.user_profiles USING btree (enabled);

CREATE INDEX idx_user_profiles_user_id ON public.user_profiles USING btree (user_id);

CREATE UNIQUE INDEX user_profiles_pkey ON public.user_profiles USING btree (profile_id);

CREATE UNIQUE INDEX user_profiles_user_id_key ON public.user_profiles USING btree (user_id);

alter table "public"."file_conversions" add constraint "file_conversions_pkey" PRIMARY KEY using index "file_conversions_pkey";

alter table "public"."files" add constraint "files_pkey" PRIMARY KEY using index "files_pkey";

alter table "public"."user_profiles" add constraint "user_profiles_pkey" PRIMARY KEY using index "user_profiles_pkey";

alter table "public"."file_conversions" add constraint "file_conversions_file_id_fkey" FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE not valid;

alter table "public"."file_conversions" validate constraint "file_conversions_file_id_fkey";

alter table "public"."file_conversions" add constraint "file_conversions_job_completion_check" CHECK (((job_completion >= 0) AND (job_completion <= 100))) not valid;

alter table "public"."file_conversions" validate constraint "file_conversions_job_completion_check";

alter table "public"."files" add constraint "files_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."files" validate constraint "files_user_id_fkey";

alter table "public"."user_profiles" add constraint "user_profiles_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."user_profiles" validate constraint "user_profiles_user_id_fkey";

alter table "public"."user_profiles" add constraint "user_profiles_user_id_key" UNIQUE using index "user_profiles_user_id_key";

set check_function_bodies = off;

CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
    INSERT INTO public.user_profiles (user_id)
    VALUES (NEW.id);
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_file_conversions_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_user_profiles_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$
;

grant delete on table "public"."file_conversions" to "anon";

grant insert on table "public"."file_conversions" to "anon";

grant references on table "public"."file_conversions" to "anon";

grant select on table "public"."file_conversions" to "anon";

grant trigger on table "public"."file_conversions" to "anon";

grant truncate on table "public"."file_conversions" to "anon";

grant update on table "public"."file_conversions" to "anon";

grant delete on table "public"."file_conversions" to "authenticated";

grant insert on table "public"."file_conversions" to "authenticated";

grant references on table "public"."file_conversions" to "authenticated";

grant select on table "public"."file_conversions" to "authenticated";

grant trigger on table "public"."file_conversions" to "authenticated";

grant truncate on table "public"."file_conversions" to "authenticated";

grant update on table "public"."file_conversions" to "authenticated";

grant delete on table "public"."file_conversions" to "service_role";

grant insert on table "public"."file_conversions" to "service_role";

grant references on table "public"."file_conversions" to "service_role";

grant select on table "public"."file_conversions" to "service_role";

grant trigger on table "public"."file_conversions" to "service_role";

grant truncate on table "public"."file_conversions" to "service_role";

grant update on table "public"."file_conversions" to "service_role";

grant delete on table "public"."files" to "anon";

grant insert on table "public"."files" to "anon";

grant references on table "public"."files" to "anon";

grant select on table "public"."files" to "anon";

grant trigger on table "public"."files" to "anon";

grant truncate on table "public"."files" to "anon";

grant update on table "public"."files" to "anon";

grant delete on table "public"."files" to "authenticated";

grant insert on table "public"."files" to "authenticated";

grant references on table "public"."files" to "authenticated";

grant select on table "public"."files" to "authenticated";

grant trigger on table "public"."files" to "authenticated";

grant truncate on table "public"."files" to "authenticated";

grant update on table "public"."files" to "authenticated";

grant delete on table "public"."files" to "service_role";

grant insert on table "public"."files" to "service_role";

grant references on table "public"."files" to "service_role";

grant select on table "public"."files" to "service_role";

grant trigger on table "public"."files" to "service_role";

grant truncate on table "public"."files" to "service_role";

grant update on table "public"."files" to "service_role";

grant delete on table "public"."user_profiles" to "anon";

grant insert on table "public"."user_profiles" to "anon";

grant references on table "public"."user_profiles" to "anon";

grant select on table "public"."user_profiles" to "anon";

grant trigger on table "public"."user_profiles" to "anon";

grant truncate on table "public"."user_profiles" to "anon";

grant update on table "public"."user_profiles" to "anon";

grant delete on table "public"."user_profiles" to "authenticated";

grant insert on table "public"."user_profiles" to "authenticated";

grant references on table "public"."user_profiles" to "authenticated";

grant select on table "public"."user_profiles" to "authenticated";

grant trigger on table "public"."user_profiles" to "authenticated";

grant truncate on table "public"."user_profiles" to "authenticated";

grant update on table "public"."user_profiles" to "authenticated";

grant delete on table "public"."user_profiles" to "service_role";

grant insert on table "public"."user_profiles" to "service_role";

grant references on table "public"."user_profiles" to "service_role";

grant select on table "public"."user_profiles" to "service_role";

grant trigger on table "public"."user_profiles" to "service_role";

grant truncate on table "public"."user_profiles" to "service_role";

grant update on table "public"."user_profiles" to "service_role";

create policy "Users can view conversions for their own files."
on "public"."file_conversions"
as permissive
for select
to authenticated
using (((EXISTS ( SELECT 1
   FROM files
  WHERE ((files.file_id = file_conversions.file_id) AND (files.user_id = ( SELECT auth.uid() AS uid))))) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Users can create files."
on "public"."files"
as permissive
for insert
to authenticated
with check (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Users can delete their own files."
on "public"."files"
as permissive
for delete
to authenticated
using (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Users can see their own files only."
on "public"."files"
as permissive
for select
to public
using (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Users can update their own files."
on "public"."files"
as permissive
for update
to authenticated
using (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))))
with check (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = ( SELECT auth.uid() AS uid)) AND (user_profiles.enabled = true))))));


create policy "Service role can manage all profiles."
on "public"."user_profiles"
as permissive
for all
to service_role
using (true)
with check (true);


create policy "Users can update their own profile."
on "public"."user_profiles"
as permissive
for update
to authenticated
using ((( SELECT auth.uid() AS uid) = user_id))
with check ((( SELECT auth.uid() AS uid) = user_id));


create policy "Users can view their own profile."
on "public"."user_profiles"
as permissive
for select
to authenticated
using ((( SELECT auth.uid() AS uid) = user_id));


CREATE TRIGGER trigger_update_file_conversions_updated_at BEFORE UPDATE ON public.file_conversions FOR EACH ROW EXECUTE FUNCTION update_file_conversions_updated_at();

CREATE TRIGGER trigger_update_user_profiles_updated_at BEFORE UPDATE ON public.user_profiles FOR EACH ROW EXECUTE FUNCTION update_user_profiles_updated_at();

CREATE TRIGGER trigger_handle_new_user AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION handle_new_user();


