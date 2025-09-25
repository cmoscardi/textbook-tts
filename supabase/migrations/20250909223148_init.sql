create table "public"."celery_taskmeta" (
    "id" integer not null,
    "task_id" character varying(155),
    "status" character varying(50),
    "result" bytea,
    "date_done" timestamp without time zone,
    "traceback" text,
    "name" character varying(155),
    "args" bytea,
    "kwargs" bytea,
    "worker" character varying(155),
    "retries" integer,
    "queue" character varying(155)
);


alter table "public"."celery_taskmeta" enable row level security;

create table "public"."celery_tasksetmeta" (
    "id" integer not null,
    "taskset_id" character varying(155),
    "result" bytea,
    "date_done" timestamp without time zone
);


alter table "public"."celery_tasksetmeta" enable row level security;

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

CREATE UNIQUE INDEX files_pkey ON public.files USING btree (file_id);

alter table "public"."files" add constraint "files_pkey" PRIMARY KEY using index "files_pkey";

alter table "public"."files" add constraint "files_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."files" validate constraint "files_user_id_fkey";

grant delete on table "public"."celery_taskmeta" to "anon";

grant insert on table "public"."celery_taskmeta" to "anon";

grant references on table "public"."celery_taskmeta" to "anon";

grant select on table "public"."celery_taskmeta" to "anon";

grant trigger on table "public"."celery_taskmeta" to "anon";

grant truncate on table "public"."celery_taskmeta" to "anon";

grant update on table "public"."celery_taskmeta" to "anon";

grant delete on table "public"."celery_taskmeta" to "authenticated";

grant insert on table "public"."celery_taskmeta" to "authenticated";

grant references on table "public"."celery_taskmeta" to "authenticated";

grant select on table "public"."celery_taskmeta" to "authenticated";

grant trigger on table "public"."celery_taskmeta" to "authenticated";

grant truncate on table "public"."celery_taskmeta" to "authenticated";

grant update on table "public"."celery_taskmeta" to "authenticated";

grant delete on table "public"."celery_taskmeta" to "service_role";

grant insert on table "public"."celery_taskmeta" to "service_role";

grant references on table "public"."celery_taskmeta" to "service_role";

grant select on table "public"."celery_taskmeta" to "service_role";

grant trigger on table "public"."celery_taskmeta" to "service_role";

grant truncate on table "public"."celery_taskmeta" to "service_role";

grant update on table "public"."celery_taskmeta" to "service_role";

grant delete on table "public"."celery_tasksetmeta" to "anon";

grant insert on table "public"."celery_tasksetmeta" to "anon";

grant references on table "public"."celery_tasksetmeta" to "anon";

grant select on table "public"."celery_tasksetmeta" to "anon";

grant trigger on table "public"."celery_tasksetmeta" to "anon";

grant truncate on table "public"."celery_tasksetmeta" to "anon";

grant update on table "public"."celery_tasksetmeta" to "anon";

grant delete on table "public"."celery_tasksetmeta" to "authenticated";

grant insert on table "public"."celery_tasksetmeta" to "authenticated";

grant references on table "public"."celery_tasksetmeta" to "authenticated";

grant select on table "public"."celery_tasksetmeta" to "authenticated";

grant trigger on table "public"."celery_tasksetmeta" to "authenticated";

grant truncate on table "public"."celery_tasksetmeta" to "authenticated";

grant update on table "public"."celery_tasksetmeta" to "authenticated";

grant delete on table "public"."celery_tasksetmeta" to "service_role";

grant insert on table "public"."celery_tasksetmeta" to "service_role";

grant references on table "public"."celery_tasksetmeta" to "service_role";

grant select on table "public"."celery_tasksetmeta" to "service_role";

grant trigger on table "public"."celery_tasksetmeta" to "service_role";

grant truncate on table "public"."celery_tasksetmeta" to "service_role";

grant update on table "public"."celery_tasksetmeta" to "service_role";

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


