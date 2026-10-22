-- CodeLens tables for Supabase (Postgres). Mirrors the Django models.
-- Safe to re-run: everything uses IF NOT EXISTS.
-- Row-level security is enabled with no policies, so the tables are reachable
-- only with the secret key / direct DB connection, never with the publishable key.

create table if not exists public.projects (
    id          bigint generated always as identity primary key,
    name        varchar(200) not null,
    created_at  timestamptz not null default now(),
    indexed     boolean not null default false
);

create table if not exists public.project_files (
    id          bigint generated always as identity primary key,
    project_id  bigint not null references public.projects(id) on delete cascade,
    path        varchar(500) not null,
    language    varchar(40) not null,
    content     text not null,
    size        integer not null,
    unique (project_id, path)
);

create table if not exists public.documents (
    id           bigint generated always as identity primary key,
    title        varchar(300) not null,
    file         varchar(500) not null,
    kind         varchar(10) not null check (kind in ('pdf', 'txt')),
    pages        integer not null default 0,
    uploaded_at  timestamptz not null default now(),
    indexed      boolean not null default false
);

create table if not exists public.chunks (
    id               bigint generated always as identity primary key,
    source_type      varchar(10) not null check (source_type in ('doc', 'code')),
    document_id      bigint references public.documents(id) on delete cascade,
    project_file_id  bigint references public.project_files(id) on delete cascade,
    text             text not null,
    page             integer,
    heading          varchar(300) not null default '',
    start_line       integer,
    end_line         integer,
    chroma_id        varchar(64) not null unique,
    check (
        (source_type = 'doc' and document_id is not null)
        or (source_type = 'code' and project_file_id is not null)
    )
);

create table if not exists public.query_logs (
    id          bigint generated always as identity primary key,
    project_id  bigint references public.projects(id) on delete set null,
    selection   text not null,
    problem     text not null default '',
    mode        varchar(20) not null,
    retrieved   jsonb not null,
    grounded    boolean not null,
    answer      jsonb,
    latency_ms  integer not null default 0,
    created_at  timestamptz not null default now()
);

create table if not exists public.llm_cache (
    id          bigint generated always as identity primary key,
    key         varchar(64) not null unique,
    model       varchar(100) not null,
    response    text not null,
    created_at  timestamptz not null default now()
);

create index if not exists project_files_project_idx on public.project_files(project_id);
create index if not exists chunks_document_idx on public.chunks(document_id);
create index if not exists chunks_project_file_idx on public.chunks(project_file_id);
create index if not exists query_logs_project_idx on public.query_logs(project_id);
create index if not exists query_logs_created_idx on public.query_logs(created_at desc);

alter table public.projects      enable row level security;
alter table public.project_files enable row level security;
alter table public.documents     enable row level security;
alter table public.chunks        enable row level security;
alter table public.query_logs    enable row level security;
alter table public.llm_cache     enable row level security;
