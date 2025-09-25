create table "public"."celery_tasksetmeta" (
    "id" integer not null,
    "taskset_id" character varying(155),
    "result" bytea,
    "date_done" timestamp without time zone
);

alter table celery_tasksetmeta enable row level security;
