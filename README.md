# SethiMacro

FastAPI backend for the SethiMacro module on SethiWay.

## Runtime environment

Required existing variables:

- `FRED_API_KEY`
- `FINNHUB_API_KEY`
- `GOOGLE_API_KEY`

The Phase 1 persistent snapshot layer does **not** require a Supabase service-role key on Render. A Supabase Edge Function performs trusted snapshot writes and the scheduled GitHub Action asks that function to refresh stale snapshot keys every six hours.

The backend can optionally write snapshots itself when `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_SERVICE_KEY`, or `SUPABASE_KEY` is present, but this is an optimisation rather than a deployment requirement.

## Cache model

SethiMacro now uses three layers:

1. Direct browser reads of public-safe Supabase snapshots for an almost immediate first useful render.
2. Persistent endpoint snapshots used by the backend after a Render restart.
3. Warm-process RAM caching for individual FRED series.

The snapshot refresh function only accepts a fixed whitelist of SethiMacro keys, fetches data from the trusted SethiMacro API itself, and writes with the Supabase service role inside the Edge Function. The browser remains SELECT-only under RLS.
