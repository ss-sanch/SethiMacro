# SethiMacro

FastAPI backend for the SethiMacro module on SethiWay.

## Runtime environment

Required existing variables:

- `FRED_API_KEY`
- `FINNHUB_API_KEY`
- `GOOGLE_API_KEY`

Phase 1 persistent snapshots also require:

- `SUPABASE_SERVICE_ROLE_KEY` — server-side only; used to upsert public-safe macro snapshots.
- `SUPABASE_URL` is optional because the SethiWay Supabase project URL is the default.

Do not expose the service-role key in frontend code. The browser uses the Supabase publishable key and RLS permits SELECT only.

## Cache model

SethiMacro now uses two cache layers:

1. Warm-process RAM caching for individual FRED series.
2. Persistent Supabase endpoint snapshots so Render restarts do not force visitors to rebuild the entire macro dashboard.

The scheduled GitHub Action refreshes the endpoint snapshots every six hours. Endpoint-specific TTLs mean slower-moving pillars can remain cached longer while market-sensitive data refreshes more often.
