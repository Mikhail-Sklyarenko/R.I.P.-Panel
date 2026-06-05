/**
 * Steam logOn + webSession (hold process). Used by farm panel launcher (B-STEAM-AUTH).
 * argv: login password shared_secret
 * stdout: JSON lines; {"event":"ready","status":"STEAM_AUTH_READY"} when session is usable
 * exit 0 only on SIGTERM after ready; exit 1 on login error
 */
"use strict";

const SteamUser = require("steam-user");
const SteamTotp = require("steam-totp");

const login = process.argv[2];
const password = process.argv[3];
const sharedSecret = process.argv[4];

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

if (!login || !password || !sharedSecret) {
  emit({ event: "error", message: "usage: steam_login.js login password shared_secret" });
  process.exit(2);
}

const client = new SteamUser();

client.logOn({
  accountName: login,
  password: password,
  twoFactorCode: SteamTotp.getAuthCode(sharedSecret),
});

client.on("loggedOn", function () {
  emit({ event: "loggedOn" });
});

client.on("webSession", function () {
  emit({ event: "webSession" });
  emit({ event: "ready", status: "STEAM_AUTH_READY" });
});

client.on("error", function (err) {
  emit({
    event: "error",
    message: String((err && err.message) || err),
    eresult: err && err.eresult,
  });
  process.exit(1);
});

process.on("SIGTERM", function () {
  try {
    client.logOff();
  } catch (_e) {
    /* ignore */
  }
  process.exit(0);
});

process.on("SIGINT", function () {
  process.emit("SIGTERM");
});
