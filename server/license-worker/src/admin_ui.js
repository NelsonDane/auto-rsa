// Operator web console served at GET /admin. A no-terminal front-end for the
// existing admin endpoints (/admin/issue, /admin/list, /admin/revoke,
// /admin/kill). It is a static, self-contained HTML page: the operator types
// the ADMIN_SECRET (kept only in their browser) and every action is sent as
// `Authorization: Bearer <secret>` to the SAME-ORIGIN admin API — so the page
// itself carries no secret and no signing code. None of this ships in the
// distributed desktop app.
//
// The inline page script deliberately uses string concatenation (no template
// literals / backticks) so this outer template literal needs no escaping.
export const ADMIN_UI_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>AutoRSA — License Console</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: #0f1115; color: #e6e8ec;
  }
  main { max-width: 760px; margin: 0 auto; padding: 24px 18px 64px; }
  h1 { font-size: 22px; margin: 0 0 2px; }
  h2 { font-size: 16px; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }
  .sub { color: #9aa2ad; margin: 0 0 24px; }
  section { background: #171a21; border: 1px solid #262b34; border-radius: 12px; padding: 18px; margin: 0 0 16px; }
  label { display: block; margin: 0 0 12px; font-size: 13px; color: #b8c0cc; }
  label.chk { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  input[type=text], input[type=password], input[type=number], select {
    width: 100%; margin-top: 5px; padding: 10px 12px; font-size: 15px;
    background: #0f1115; color: #e6e8ec; border: 1px solid #2f3641; border-radius: 8px;
  }
  label.chk input { width: auto; margin: 0; }
  button {
    padding: 10px 16px; font-size: 14px; font-weight: 600; border: 0; border-radius: 8px;
    cursor: pointer; background: #2a3140; color: #e6e8ec;
  }
  button.primary { background: #3b82f6; color: #fff; }
  button.danger { background: #ef4444; color: #fff; }
  button.ok { background: #1f9d55; color: #fff; }
  button.ghost { background: transparent; border: 1px solid #2f3641; color: #b8c0cc; padding: 6px 12px; font-size: 13px; }
  button:hover { filter: brightness(1.1); }
  .hint { color: #8a93a0; font-size: 12.5px; margin: 6px 0 0; }
  .err { color: #f87171; font-size: 13px; margin: 8px 0 0; }
  .ok-txt { color: #4ade80; }
  .key { margin-top: 14px; padding: 16px; background: #0f1115; border: 1px solid #2f3641; border-radius: 10px; }
  .keyval { font: 700 22px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: 1px; word-break: break-all; color: #7dd3fc; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 8px; border-bottom: 1px solid #232833; vertical-align: top; }
  th { color: #8a93a0; font-weight: 600; }
  .row-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
  @media (max-width: 560px) { table, thead, tbody, th, td, tr { display: block; } th { display: none; } td { border: 0; padding: 2px 0; } tr { border-bottom: 1px solid #232833; padding: 10px 0; } }
</style>
</head>
<body>
<main>
  <h1>AutoRSA License Console</h1>
  <p class="sub">Issue and manage license keys — no terminal needed.</p>

  <section>
    <label>Admin secret
      <input id="secret" type="password" placeholder="rsa_admin_…" autocomplete="off" spellcheck="false">
    </label>
    <label class="chk"><input id="remember" type="checkbox"> Remember on this device</label>
    <p class="hint">Stored only in your browser. Anyone with this secret can issue and revoke licenses — keep it private.</p>
  </section>

  <section>
    <h2>Generate a key</h2>
    <label>Type
      <select id="tier">
        <option value="friend_main">Friend — Main (many brokers, 1 account each)</option>
        <option value="friend_lite">Friend — Lite (one broker at a time)</option>
        <option value="operator">Operator (you — unlimited, all brokers)</option>
        <option value="advanced">Advanced (up to 5 brokers)</option>
        <option value="basic">Basic (1 broker)</option>
      </select>
    </label>
    <label>Notes (optional — e.g. who it's for)
      <input id="notes" type="text" placeholder="Alex — birthday gift">
    </label>
    <label>Valid for (days — blank = 365)
      <input id="days" type="number" min="1" placeholder="365">
    </label>
    <button id="gen" class="primary">Generate key</button>
    <div id="genResult"></div>
  </section>

  <section>
    <h2>Existing licenses <button id="refresh" class="ghost">Refresh</button></h2>
    <div id="listResult"><p class="hint">Click Refresh to load.</p></div>
  </section>

  <section>
    <h2>Kill switch</h2>
    <p id="killState" class="hint">—</p>
    <label>Message shown to users when paused
      <input id="killMsg" type="text" placeholder="Paused for a quick fix — back shortly.">
    </label>
    <label>Only pause builds at or below version (optional)
      <input id="killMin" type="text" placeholder="0.1.0">
    </label>
    <div class="row-actions">
      <button id="killOn" class="danger">Turn kill switch ON</button>
      <button id="killOff" class="ok">Turn OFF</button>
    </div>
    <div id="killResult"></div>
  </section>
</main>
<script>
(function(){
  var $ = function(id){ return document.getElementById(id); };
  var LS = "rsa_admin_secret";
  var saved = localStorage.getItem(LS) || sessionStorage.getItem(LS) || "";
  if (saved) { $("secret").value = saved; if (localStorage.getItem(LS)) $("remember").checked = true; }
  function secret(){ return $("secret").value.trim(); }
  function persist(){
    var s = secret();
    sessionStorage.setItem(LS, s);
    if ($("remember").checked && s) localStorage.setItem(LS, s); else localStorage.removeItem(LS);
  }
  $("secret").addEventListener("change", persist);
  $("remember").addEventListener("change", persist);

  function api(method, path, body){
    persist();
    if (!secret()) return Promise.reject(new Error("Enter the admin secret first."));
    var opts = { method: method, headers: { "authorization": "Bearer " + secret() } };
    if (body) { opts.headers["content-type"] = "application/json"; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function(r){
      return r.json().catch(function(){ return {}; }).then(function(j){
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }
  function esc(s){
    return String(s == null ? "" : s).replace(/[&<>"]/g, function(c){
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  $("gen").addEventListener("click", function(){
    var body = { tier: $("tier").value };
    var notes = $("notes").value.trim();
    if (notes) body.notes = notes;
    var days = parseInt($("days").value, 10);
    if (days && days > 0) {
      body.expires_at = new Date(Date.now() + days * 86400000).toISOString().replace(/\\.\\d{3}Z$/, "Z");
    }
    $("genResult").innerHTML = '<p class="hint">Generating…</p>';
    api("POST", "/admin/issue", body).then(function(j){
      $("genResult").innerHTML =
        '<div class="key"><div class="keyval" id="keyval">' + esc(j.license_key) + "</div>" +
        '<div class="row-actions"><button class="ghost" id="copyKey">Copy key</button></div>' +
        '<p class="hint">Type: ' + esc(j.tier) + " · Expires: " + esc((j.expires_at || "").slice(0, 10)) +
        "<br>Give this key to your friend — they paste it in the app's <b>License</b> section.</p></div>";
      $("copyKey").addEventListener("click", function(){
        navigator.clipboard.writeText(j.license_key).then(function(){ $("copyKey").textContent = "Copied ✓"; });
      });
      if ($("listResult").dataset.loaded) loadList();
    }).catch(function(e){ $("genResult").innerHTML = '<p class="err">' + esc(e.message) + "</p>"; });
  });

  function loadList(){
    $("listResult").innerHTML = '<p class="hint">Loading…</p>';
    api("GET", "/admin/list").then(function(j){
      $("listResult").dataset.loaded = "1";
      var rows = (j.licenses || []).slice().sort(function(a, b){ return (b.issued_at || "").localeCompare(a.issued_at || ""); });
      if (!rows.length) { $("listResult").innerHTML = '<p class="hint">No licenses yet.</p>'; return; }
      var h = "<table><thead><tr><th>Key</th><th>Type</th><th>Status</th><th>Bound</th><th>Notes</th><th>Expires</th><th></th></tr></thead><tbody>";
      rows.forEach(function(r){
        var revoked = r.status === "revoked";
        h += "<tr>" +
          '<td class="mono">' + esc(r.license_key) + "</td>" +
          "<td>" + esc(r.tier) + "</td>" +
          "<td>" + (revoked ? '<span class="err">revoked</span>' : '<span class="ok-txt">active</span>') + "</td>" +
          "<td>" + (r.hardware_id ? "yes" : "—") + "</td>" +
          "<td>" + esc(r.notes) + "</td>" +
          '<td class="mono">' + esc((r.expires_at || "").slice(0, 10)) + "</td>" +
          "<td>" + (revoked ? "" : '<button class="ghost revoke" data-id="' + esc(r.license_id) + '">Revoke</button>') + "</td>" +
          "</tr>";
      });
      h += "</tbody></table>";
      $("listResult").innerHTML = h;
      Array.prototype.forEach.call(document.querySelectorAll(".revoke"), function(btn){
        btn.addEventListener("click", function(){
          if (!confirm("Revoke this license? The friend stops trading on their next check.")) return;
          api("POST", "/admin/revoke", { license_id: btn.getAttribute("data-id") }).then(loadList)
            .catch(function(e){ alert(e.message); });
        });
      });
    }).catch(function(e){ $("listResult").innerHTML = '<p class="err">' + esc(e.message) + "</p>"; });
  }
  $("refresh").addEventListener("click", loadList);

  function loadKill(){
    fetch("/killswitch").then(function(r){ return r.json(); }).then(function(k){
      $("killState").innerHTML = k.active
        ? '<span class="err">● ON</span> — ' + esc(k.message) + (k.min_app_version ? " (≤ " + esc(k.min_app_version) + ")" : "")
        : '<span class="ok-txt">● OFF</span> — trading allowed';
    }).catch(function(){});
  }
  $("killOn").addEventListener("click", function(){
    if (!confirm("Turn the kill switch ON? This pauses trading for affected builds.")) return;
    api("POST", "/admin/kill", { active: true, message: $("killMsg").value.trim(), min_app_version: $("killMin").value.trim() })
      .then(function(){ loadKill(); $("killResult").innerHTML = '<p class="ok-txt">Kill switch ON.</p>'; })
      .catch(function(e){ $("killResult").innerHTML = '<p class="err">' + esc(e.message) + "</p>"; });
  });
  $("killOff").addEventListener("click", function(){
    api("POST", "/admin/kill", { active: false, message: $("killMsg").value.trim() })
      .then(function(){ loadKill(); $("killResult").innerHTML = '<p class="ok-txt">Kill switch OFF.</p>'; })
      .catch(function(e){ $("killResult").innerHTML = '<p class="err">' + esc(e.message) + "</p>"; });
  });
  loadKill();
})();
</script>
</body>
</html>`;
