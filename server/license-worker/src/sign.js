/**
 * Ed25519 signing for license tokens (node:crypto).
 *
 * The canonical JSON here MUST stay byte-identical to
 * src/license/verify.py :: canonical_bytes (sorted keys, no whitespace,
 * non-ASCII preserved). This is the single most important compatibility
 * surface — server/license-worker/golden/golden.mjs locks it against a
 * checked-in vector, and it is proven equal to Python's signature.
 */

import { createPrivateKey, createPublicKey, sign, verify } from "node:crypto";

export function canonicalize(o) {
  if (o === null || typeof o !== "object") return o;
  if (Array.isArray(o)) return o.map(canonicalize);
  const out = {};
  for (const k of Object.keys(o).sort()) out[k] = canonicalize(o[k]);
  return out;
}

export function canonicalJson(payload) {
  // JSON.stringify with no space arg => separators (",", ":"), matching
  // Python separators=(",", ":"). Non-ASCII is left unescaped, matching
  // ensure_ascii=False.
  return JSON.stringify(canonicalize(payload));
}

export function signToken(payload, pem) {
  const key = createPrivateKey(pem);
  // Ed25519 is PureEdDSA: algorithm arg is null, output is the raw 64-byte
  // signature — the same bytes cryptography's Ed25519PrivateKey.sign yields.
  const sig = sign(null, Buffer.from(canonicalJson(payload), "utf8"), key);
  return sig.toString("base64url");
}

export function verifyToken(token, pem) {
  try {
    if (!token || typeof token !== "object") return false;
    const { payload, signature } = token;
    if (!payload || typeof signature !== "string") return false;
    const pub = createPublicKey(createPrivateKey(pem));
    return verify(
      null,
      Buffer.from(canonicalJson(payload), "utf8"),
      pub,
      Buffer.from(signature, "base64url"),
    );
  } catch {
    return false;
  }
}
