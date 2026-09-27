import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const ENDPOINTS: Record<string, { path: string; ttl: number }> = {
  "pillar-jobs": { path: "pillar-jobs", ttl: 43200 },
  "pillar-rates": { path: "pillar-rates", ttl: 21600 },
  "pillar-gdp": { path: "pillar-gdp", ttl: 43200 },
  "pillar-fx": { path: "pillar-fx", ttl: 14400 },
  "quant-signals": { path: "quant-signals", ttl: 14400 },
  "calendar-timeline": { path: "calendar-timeline", ttl: 21600 },
  "pillar-yield-curve": { path: "pillar-yield-curve", ttl: 21600 },
  "pillar-commodities": { path: "pillar-commodities", ttl: 21600 },
  "macro-ai": { path: "macro-ai", ttl: 43200 },
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const TABLE = "sethimacro_public_snapshots";
const MACRO_API = "https://sethimacro.sethiway.com/api";

function serviceHeaders(extra: Record<string, string> = {}) {
  return {
    apikey: SERVICE_KEY,
    Authorization: `Bearer ${SERVICE_KEY}`,
    "Content-Type": "application/json",
    ...extra,
  };
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return Response.json({ error: "POST required" }, { status: 405 });
  }

  let body: { key?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const key = String(body.key || "");
  const config = ENDPOINTS[key];
  if (!config) {
    return Response.json({ error: "Unknown snapshot key" }, { status: 400 });
  }

  try {
    const lookup = new URL(`${SUPABASE_URL}/rest/v1/${TABLE}`);
    lookup.searchParams.set("snapshot_key", `eq.${key}`);
    lookup.searchParams.set("select", "generated_at,ttl_seconds");
    lookup.searchParams.set("limit", "1");

    const existingRes = await fetch(lookup, { headers: serviceHeaders() });
    if (existingRes.ok) {
      const rows = await existingRes.json();
      const row = Array.isArray(rows) ? rows[0] : null;
      if (row?.generated_at) {
        const ageSeconds = Math.max(0, (Date.now() - Date.parse(row.generated_at)) / 1000);
        const ttl = Number(row.ttl_seconds || config.ttl);
        if (Number.isFinite(ageSeconds) && ageSeconds < ttl) {
          return Response.json({
            key,
            status: "fresh",
            age_seconds: Math.round(ageSeconds),
            ttl_seconds: ttl,
          });
        }
      }
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    let upstream: Response;
    try {
      upstream = await fetch(`${MACRO_API}/${config.path}`, {
        signal: controller.signal,
        headers: { "User-Agent": "SethiMacro Supabase snapshot refresher/1.0" },
      });
    } finally {
      clearTimeout(timer);
    }

    if (!upstream.ok) {
      return Response.json({ key, error: `Macro API returned HTTP ${upstream.status}` }, { status: 502 });
    }

    const payload = await upstream.json();
    if (!payload || typeof payload !== "object" || Array.isArray(payload) || Object.keys(payload).length === 0 || payload.error) {
      return Response.json({ key, error: "Macro API returned an unusable payload" }, { status: 502 });
    }

    const now = new Date().toISOString();
    const writeRes = await fetch(
      `${SUPABASE_URL}/rest/v1/${TABLE}?on_conflict=snapshot_key`,
      {
        method: "POST",
        headers: serviceHeaders({ Prefer: "resolution=merge-duplicates,return=minimal" }),
        body: JSON.stringify({
          snapshot_key: key,
          payload,
          generated_at: now,
          ttl_seconds: config.ttl,
          source_status: "ok",
          updated_at: now,
        }),
      },
    );

    if (!writeRes.ok) {
      const detail = (await writeRes.text()).slice(0, 500);
      return Response.json({ key, error: "Snapshot write failed", detail }, { status: 500 });
    }

    return Response.json({ key, status: "refreshed", generated_at: now });
  } catch (error) {
    return Response.json({ key, error: String(error) }, { status: 500 });
  }
});
