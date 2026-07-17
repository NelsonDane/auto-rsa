/**
 * Ed25519 signing for license tokens — WebCrypto (crypto.subtle).
 *
 * IMPORTANT: use WebCrypto, NOT node:crypto. Cloudflare Workers route
 * node:crypto through the unenv polyfill, whose `sign` is a stub that
 * throws "[unenv] crypto.sign is not implemented yet!". crypto.subtle is
 * native in workerd and supports Ed25519, so it works on the Worker (and
 * in Node 18+/22, so the golden test still runs locally).
 *
 * The canonical JSON here MUST stay byte-identical to
 * src/license/verify.py :: canonical_bytes (sorted keys, no whitespace,
 * non-ASCII preserved). Ed25519 is deterministic, so the signature over
 * those bytes is identical to Python `cryptography`'s — the checked-in
 * golden vector (golden/golden.mjs + edgar_tests/license_golden_test.py)
 * proves it.
 */

export function canonicalize(o) {
  if (o === null || typeof o !== "object") return o;
  if (Array.isArray(o)) return o.map(canonicalize);
  const out = {};
  for (const k of Object.keys(o).sort()) out[k] = canonicalize(o[k]);
  return out;
}

export function canonicalJson(payload) {
  return JSON.stringify(canonicalize(payload));
}

// PKCS8 PEM ("-----BEGIN PRIVATE KEY-----" ...) -> raw DER bytes.
function pemToDer(pem) {
  const body = String(pem)
    .replace(/-----BEGIN [\s\S]*?-----/, "")
    .replace(/-----END [\s\S]*?-----/, "")
    .replace(/[^A-Za-z0-9+/=]/g, "");
  const bin = atob(body);
  const der = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) der[i] = bin.charCodeAt(i);
  return der;
}

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// importKey is async, so signing is async. Callers await it.
async function importSigningKey(pem) {
  return crypto.subtle.importKey(
    "pkcs8", pemToDer(pem), { name: "Ed25519" }, false, ["sign"],
  );
}

export async function signToken(payload, pem) {
  const key = await importSigningKey(pem);
  const data = new TextEncoder().encode(canonicalJson(payload));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, data));
  return b64url(sig);
}

export async function verifyToken(token, pem) {
  // Ed25519 is deterministic: re-signing the payload and comparing is a
  // valid verification and needs only the (already-held) private key.
  try {
    if (!token || typeof token !== "object") return false;
    const { payload, signature } = token;
    if (!payload || typeof signature !== "string") return false;
    return (await signToken(payload, pem)) === signature;
  } catch {
    return false;
  }
}
