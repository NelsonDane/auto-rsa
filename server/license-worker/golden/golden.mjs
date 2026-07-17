/**
 * Golden-vector test — run BEFORE every deploy:  npm run test:golden
 *
 * Proves the Worker's signing (src/sign.js) still produces the exact
 * signature the desktop app's verify.py expects, using a checked-in
 * throwaway TEST key. If this fails, the Worker and the Python verifier
 * have diverged (usually a canonical-JSON change) — DO NOT DEPLOY until
 * it is green again, or every friend's activation will fail.
 *
 * No dependencies; uses only node:crypto + the Worker's own sign module.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createPrivateKey } from "node:crypto";
import { signToken, verifyToken, canonicalJson } from "../src/sign.js";

const here = dirname(fileURLToPath(import.meta.url));
const golden = JSON.parse(readFileSync(join(here, "golden.json"), "utf8"));

// Rebuild the TEST key from the committed seed (no private-key file to
// commit). Ed25519 JWK: d = seed (base64url), x = raw public (base64url).
// Then export to an in-memory PEM (never written to disk) — the exact
// input shape the Worker's signToken(pem) takes in production.
const seed = Buffer.from(golden.seed_b64, "base64");
const x = Buffer.from(golden.public_key_b64, "base64");
const testKey = createPrivateKey({
  key: { kty: "OKP", crv: "Ed25519", d: seed.toString("base64url"), x: x.toString("base64url") },
  format: "jwk",
});
const pem = testKey.export({ type: "pkcs8", format: "pem" });

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`  ok   ${name}`);
  } else {
    console.error(`  FAIL ${name}`);
    failures++;
  }
}

// 1. Re-signing the golden payload reproduces the golden signature byte-for-byte.
const sig = await signToken(golden.payload, pem);
check("signature matches the golden vector", sig === golden.signature);

// 2. The Worker verifies its own token (the /refresh trust path).
check(
  "verifyToken accepts a freshly signed token",
  await verifyToken({ payload: golden.payload, signature: sig }, pem),
);

// 3. Tampering is rejected.
const tampered = { ...golden.payload, tier: "operator" };
check(
  "verifyToken rejects a tampered payload",
  !(await verifyToken({ payload: tampered, signature: sig }, pem)),
);

// 4. Canonical JSON has no spaces and sorted keys (the compatibility surface).
const canon = canonicalJson(golden.payload);
check("canonical JSON has no whitespace", !/\s/.test(canon));
check(
  "canonical JSON keys are sorted",
  canon.indexOf('"expires_at"') < canon.indexOf('"tier"'),
);

if (failures) {
  console.error(`\nGOLDEN VECTOR FAILED (${failures}) — do NOT deploy.`);
  process.exit(1);
}
console.log("\nGolden vector OK — safe to deploy.");
