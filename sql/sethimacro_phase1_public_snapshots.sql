create table if not exists public.sethimacro_public_snapshots (
    snapshot_key text primary key,
    payload jsonb not null,
    generated_at timestamptz not null default now(),
    ttl_seconds integer not null default 43200 check (ttl_seconds >= 300),
    source_status text not null default 'ok',
    updated_at timestamptz not null default now()
);

create index if not exists sethimacro_public_snapshots_updated_at_idx
    on public.sethimacro_public_snapshots (updated_at desc);

alter table public.sethimacro_public_snapshots enable row level security;

drop policy if exists "Public read SethiMacro snapshots" on public.sethimacro_public_snapshots;
create policy "Public read SethiMacro snapshots"
    on public.sethimacro_public_snapshots
    for select
    to anon, authenticated
    using (true);
