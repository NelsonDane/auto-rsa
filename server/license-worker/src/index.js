/**
 * auto-rsa license server (Cloudflare Worker).
 *
 * Signs short-lived Ed25519 license tokens the desktop app verifies with
 * its embedded public key (src/license/verify.py), and serves the remote
 * KILL SWITCH the operator flips when a crucial bug is found.
 *
 * The signature contract is proven cross-language: this Worker's
 * WebCrypto (crypto.subtle) Ed25519 signature over the canonical JSON is
 * byte-identical to Python `cryptography`'s, and verifies against the
 * shipped verify.py. (WebCrypto, not node:crypto — see src/sign.js.)
 * See server/license-worker/golden/golden.mjs and docs/CLOUDFLARE_LICENSE_BUILD.md.
 *
 * Endpoints:
 *   POST /activate    { license_key, hardware_id, hostname_hash, app_version, platform }
 *   POST /refresh     { token }
 *   GET  /killswitch  [?app_version=]
 *   GET  /admin          operator web console (no-terminal keygen UI)
 *   POST /admin/issue    (Bearer ADMIN_SECRET)  { tier, notes?, expires_at? }
 *   POST /admin/revoke   (Bearer)  { license_id }
 *   POST /admin/kill     (Bearer)  { active, message?, min_app_version? }
 *   POST /admin/rebind   (Bearer)  { license_id, hardware_id }
 *   GET  /admin/list     (Bearer)
 *
 * Bindings (wrangler.toml):   KV namespace  LICENSES
 * Secrets (wrangler secret):  SIGNING_KEY_PEM (Ed25519 private PEM), ADMIN_SECRET
 */

import { signToken, verifyToken as verifyOwnToken } from "./sign.js";
import { ADMIN_UI_HTML } from "./admin_ui.js";

// Token lifetime — short, so a revoke/kill bites on the next refresh.
const TOKEN_TTL_DAYS = 30;
const VALID_TIERS = new Set([
  "basic", "advanced", "operator", "friend_lite", "friend_main",
]);
// Parent-broker cap per tier (null = unlimited). Must mirror
// src/license/tiers.py :: TIER_CAPS.
const TIER_CAP = {
  basic: 1, advanced: 5, operator: null, friend_lite: 1, friend_main: null,
};

// ---- helpers -----------------------------------------------------------
const now = () => new Date();
const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, "Z");

function addDays(d, n) {
  const c = new Date(d.getTime());
  c.setUTCDate(c.getUTCDate() + n);
  return c;
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// base32 (RFC4648, no padding, no confusing chars removed for simplicity)
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
function licenseKey() {
  // 12 base32 chars (~60 bits), groups of 4: rsa-XXXX-XXXX-XXXX
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  let s = "";
  for (const b of bytes) s += B32[b & 31];
  return `rsa-${s.match(/.{1,4}/g).join("-")}`;
}

// dotted-numeric version compare: -1 (a<b) / 0 / 1 (a>b). Non-numeric -> 0-safe.
function cmpVersion(a, b) {
  const pa = String(a || "").split(".").map((x) => parseInt(x, 10) || 0);
  const pb = String(b || "").split(".").map((x) => parseInt(x, 10) || 0);
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

async function killState(env, appVersion) {
  const ks = await env.LICENSES.get("killswitch:global", "json");
  if (!ks || !ks.active) return { active: false, message: "", min_app_version: "" };
  // min_app_version present => only kill builds AT OR BELOW it (the buggy ones).
  if (ks.min_app_version && appVersion && cmpVersion(appVersion, ks.min_app_version) > 0) {
    return { active: false, message: "", min_app_version: ks.min_app_version };
  }
  return { active: true, message: ks.message || "Paused by the operator.", min_app_version: ks.min_app_version || "" };
}

async function audit(env, licenseId, event) {
  const ts = iso(now());
  // 90-day TTL; best-effort, never blocks the response.
  await env.LICENSES.put(`audit:${licenseId}:${ts}`, JSON.stringify(event), {
    expirationTtl: 60 * 60 * 24 * 90,
  });
}

function tokenPayload(rec) {
  const expires = addDays(now(), TOKEN_TTL_DAYS);
  const licExp = rec.expires_at ? new Date(rec.expires_at) : null;
  const eff = licExp && licExp < expires ? licExp : expires; // token never outlives the license
  return {
    tier: rec.tier,
    hardware_id: rec.hardware_id,
    license_id: rec.license_id,
    issued_at: iso(now()),
    expires_at: iso(eff),
  };
}

// ---- public endpoints --------------------------------------------------
async function handleActivate(req, env) {
  const body = await req.json().catch(() => null);
  if (!body || !body.license_key || !body.hardware_id) {
    return json({ error: "license_key and hardware_id required" }, 400);
  }
  const kill = await killState(env, body.app_version);
  if (kill.active) return json({ error: "killed", message: kill.message }, 423);

  const licenseId = await env.LICENSES.get(`key:${body.license_key}`);
  if (!licenseId) return json({ error: "unknown license key" }, 404);
  const rec = await env.LICENSES.get(`lic:${licenseId}`, "json");
  if (!rec) return json({ error: "unknown license" }, 404);
  if (rec.status === "revoked") return json({ error: "revoked" }, 410);
  if (rec.expires_at && new Date(rec.expires_at) < now()) {
    return json({ error: "license expired" }, 410);
  }

  // Hardware binding: bind on first activation, reject a different machine.
  if (!rec.hardware_id) {
    rec.hardware_id = body.hardware_id;
    await env.LICENSES.put(`lic:${licenseId}`, JSON.stringify(rec));
    await env.LICENSES.put(`hw:${body.hardware_id}`, licenseId);
  } else if (rec.hardware_id !== body.hardware_id) {
    return json({ error: "license already bound to another machine" }, 409);
  }

  const payload = tokenPayload(rec);
  const signature = await signToken(payload, env.SIGNING_KEY_PEM);
  await audit(env, licenseId, { event: "activate", platform: body.platform, app_version: body.app_version });
  return json({ payload, signature, account_cap: TIER_CAP[rec.tier] ?? null });
}

async function handleRefresh(req, env) {
  const body = await req.json().catch(() => null);
  const token = body && body.token;
  if (!(await verifyOwnToken(token, env.SIGNING_KEY_PEM))) {
    return json({ error: "invalid token" }, 401);
  }
  const p = token.payload;
  const kill = await killState(env, body.app_version);
  if (kill.active) return json({ error: "killed", message: kill.message }, 423);

  const rec = await env.LICENSES.get(`lic:${p.license_id}`, "json");
  if (!rec) return json({ error: "unknown license" }, 404);
  if (rec.status === "revoked") return json({ error: "revoked" }, 410);
  if (rec.hardware_id !== p.hardware_id) return json({ error: "hardware mismatch" }, 409);
  if (rec.expires_at && new Date(rec.expires_at) < now()) {
    return json({ error: "license expired" }, 410);
  }

  const payload = tokenPayload(rec);
  const signature = await signToken(payload, env.SIGNING_KEY_PEM);
  await audit(env, p.license_id, { event: "refresh" });
  return json({ payload, signature, account_cap: TIER_CAP[rec.tier] ?? null });
}

async function handleKillswitch(env, url) {
  const kill = await killState(env, url.searchParams.get("app_version"));
  return json(kill);
}

// ---- admin endpoints (Bearer ADMIN_SECRET) -----------------------------
function adminOk(req, env) {
  const auth = req.headers.get("authorization") || "";
  const tok = auth.replace(/^Bearer\s+/i, "");
  return env.ADMIN_SECRET && tok === env.ADMIN_SECRET;
}

async function handleIssue(req, env) {
  const body = await req.json().catch(() => ({}));
  const tier = String(body.tier || "");
  if (!VALID_TIERS.has(tier)) return json({ error: `tier must be one of ${[...VALID_TIERS]}` }, 400);
  const licenseId = crypto.randomUUID();
  const key = licenseKey();
  const expires_at = body.expires_at || iso(addDays(now(), 365));
  const rec = {
    license_id: licenseId,
    license_key: key,
    tier,
    hardware_id: null,
    issued_at: iso(now()),
    expires_at,
    status: "active",
    notes: body.notes || "",
  };
  await env.LICENSES.put(`lic:${licenseId}`, JSON.stringify(rec));
  await env.LICENSES.put(`key:${key}`, licenseId);
  return json({ license_key: key, license_id: licenseId, tier, expires_at });
}

async function handleRevoke(req, env) {
  const body = await req.json().catch(() => ({}));
  const rec = await env.LICENSES.get(`lic:${body.license_id}`, "json");
  if (!rec) return json({ error: "unknown license" }, 404);
  rec.status = "revoked";
  await env.LICENSES.put(`lic:${rec.license_id}`, JSON.stringify(rec));
  await audit(env, rec.license_id, { event: "revoke" });
  return json({ ok: true, license_id: rec.license_id, status: "revoked" });
}

async function handleKill(req, env) {
  const body = await req.json().catch(() => ({}));
  const state = {
    active: !!body.active,
    message: body.message || "This app is paused by the operator — check your messages.",
    min_app_version: body.min_app_version || "",
  };
  await env.LICENSES.put("killswitch:global", JSON.stringify(state));
  return json({ ok: true, ...state });
}

async function handleRebind(req, env) {
  const body = await req.json().catch(() => ({}));
  const rec = await env.LICENSES.get(`lic:${body.license_id}`, "json");
  if (!rec) return json({ error: "unknown license" }, 404);
  if (rec.hardware_id) await env.LICENSES.delete(`hw:${rec.hardware_id}`);
  rec.hardware_id = body.hardware_id || null;
  await env.LICENSES.put(`lic:${rec.license_id}`, JSON.stringify(rec));
  if (rec.hardware_id) await env.LICENSES.put(`hw:${rec.hardware_id}`, rec.license_id);
  await audit(env, rec.license_id, { event: "rebind" });
  return json({ ok: true, license_id: rec.license_id, hardware_id: rec.hardware_id });
}

async function handleList(env) {
  const out = [];
  let cursor;
  do {
    const page = await env.LICENSES.list({ prefix: "lic:", cursor });
    for (const k of page.keys) {
      const rec = await env.LICENSES.get(k.name, "json");
      if (rec) out.push(rec);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return json({ licenses: out, count: out.length });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname } = url;
    const method = request.method;
    try {
      if (method === "POST" && pathname === "/activate") return await handleActivate(request, env);
      if (method === "POST" && pathname === "/refresh") return await handleRefresh(request, env);
      if (method === "GET" && pathname === "/killswitch") return await handleKillswitch(env, url);

      // Operator web console (the page itself carries no secret; every action
      // it fires still requires the Bearer ADMIN_SECRET on /admin/*).
      if (method === "GET" && pathname === "/admin") {
        return new Response(ADMIN_UI_HTML, {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }

      if (pathname.startsWith("/admin/")) {
        if (!adminOk(request, env)) return json({ error: "unauthorized" }, 401);
        if (method === "POST" && pathname === "/admin/issue") return await handleIssue(request, env);
        if (method === "POST" && pathname === "/admin/revoke") return await handleRevoke(request, env);
        if (method === "POST" && pathname === "/admin/kill") return await handleKill(request, env);
        if (method === "POST" && pathname === "/admin/rebind") return await handleRebind(request, env);
        if (method === "GET" && pathname === "/admin/list") return await handleList(env);
      }
      return json({ error: "not found" }, 404);
    } catch (err) {
      return json({ error: "server error", detail: String(err) }, 500);
    }
  },
};
