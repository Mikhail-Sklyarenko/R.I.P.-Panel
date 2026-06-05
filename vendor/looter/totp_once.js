/**
 * One-shot TOTP for Python launcher (secret via file path, not argv).
 * Usage: node totp_once.js <path-to-secret-file>
 */
"use strict";

const SteamTotp = require("steam-totp");
const fs = require("fs");

const secretPath = process.argv[2];
if (!secretPath) {
  process.stderr.write("usage: node totp_once.js <secret-file>\n");
  process.exit(2);
}

try {
  const raw = fs.readFileSync(secretPath, "utf8");
  const secret = raw.replace(/^\uFEFF/, "").trim();
  if (!secret) {
    process.stderr.write("empty secret file\n");
    process.exit(3);
  }
  const code = SteamTotp.getAuthCode(secret);
  if (!code || String(code).length !== 5) {
    process.stderr.write("steam-totp returned invalid code length\n");
    process.exit(4);
  }
  process.stdout.write(String(code));
} catch (err) {
  process.stderr.write(String((err && err.message) || err) + "\n");
  process.exit(1);
}
