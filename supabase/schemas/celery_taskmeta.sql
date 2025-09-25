create table celery_taskmeta (                                                   
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

alter table celery_taskmeta enable row level security;
