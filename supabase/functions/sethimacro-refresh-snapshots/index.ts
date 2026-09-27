import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const API_BASE = "https://sethimacro.sethiway.com/api";
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

function validPayload(key: string, payload: unknown): payload is Record<string, unknown> {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const p = payload as Record<string, unknown>;
  if (p.error || p._partial) return false;

  const required: Record<string, string[]> = {
    "pillar-jobs": ["US_Unemp", "UK_Unemp"],
    "pillar-rates": ["Fed_Funds", "CPI", "US_10Y"],
    "pillar-gdp": ["US_GDP", "IndPro", "Retail_Sales"],
    "pillar-fx": ["gbp_usd", "eur_usd", "usd_jpy"],
    "quant-signals": ["Yield_Spread", "Sahm_Rule", "Risk_Barometer"],
    "calendar-timeline": ["past", "future"],
    "pillar-yield-curve": ["Inversion_Spread", "Term_Structure"],
    "pillar-commodities": ["Oil", "Gold", "Credit_Spread"],
    "macro-ai": ["executive_summary", "jobs", "inflation", "gdp", "fx", "commodities"],
  };
  return (required[key] || []).every((field) => field in p);
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST" && req.method !== "GET") {
    return new Response(JSON.stringify({ error: "method_not_allowed" }), {
      status: 405,
      headers: { "content-type": "application/json" },
    });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRole = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRole) {
    return new Response(JSON.stringify({ error: "supabase_runtime_not_configured" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }

  const supabase = createClient(supabaseUrl, serviceRole, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // Prevent accidental or abusive rapid refresh loops.
  const { data: newest } = await supabase
    .from("sethimacro_public_snapshots")
    .select("updated_at")
    .order("updated_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (newest?.updated_at) {
    const ageMs = Date.now() - Date.parse(newest.updated_at);
    if (Number.isFinite(ageMs) && ageMs < 10 * 60 * 1000) {
      return new Response(JSON.stringify({ status: "skipped", reason: "recent_refresh" }), {
        headers: { "content-type": "application/json" },
      });
    }
  }

  const results: Record<string, unknown> = {};
  for (const [key, config] of Object.entries(ENDPOINTS)) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), key === "calendar-timeline" ? 90000 : 45000);
    try {
      const response = await fetch(`${API_BASE}/${config.path}?force_refresh=true`, {
        headers: { "user-agent": "SethiMacro Snapshot Refresher/1.0" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();

      if (!validPayload(key, payload)) {
        results[key] = { ok: false, reason: "invalid_payload" };
        continue;
      }

      const now = new Date().toISOString();
      const { error } = await supabase
        .from("sethimacro_public_snapshots")
        .upsert({
          snapshot_key: key,
          payload,
          generated_at: now,
          ttl_seconds: config.ttl,
          source_status: "ok",
          updated_at: now,
        }, { onConflict: "snapshot_key" });

      if (error) throw error;
      results[key] = { ok: true };
    } catch (error) {
      results[key] = { ok: false, error: String(error) };
    } finally {
      clearTimeout(timer);
    }
  }

  const okCount = Object.values(results).filter((r: any) => r?.ok === true).length;
  return new Response(JSON.stringify({
    status: okCount ? "ok" : "failed",
    refreshed: okCount,
    attempted: Object.keys(ENDPOINTS).length,
    results,
  }), {
    status: okCount ? 200 : 502,
    headers: { "content-type": "application/json" },
  });
});
