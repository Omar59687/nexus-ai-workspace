"""Explicit, opt-in browser review workbench. Never mounted by default.

The UI has no saved credentials, external assets, or source-derived HTML.
It requires a trusted host to mount and a manually supplied short-lived
bearer token. It is a development workbench, not a production login flow.
"""
from __future__ import annotations

import secrets

from fastapi.responses import HTMLResponse

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus AI — Financial Evidence Review</title>
<style>
:root {font-family:system-ui,sans-serif;color-scheme:light dark}
body {max-width:1080px;margin:2rem auto;padding:0 1rem;line-height:1.5}
header,section {border:1px solid #aaa5;border-radius:10px;padding:1rem;margin:1rem 0}
h1 {font-size:1.6rem} h2 {font-size:1.2rem}
label {display:block;margin:.6rem 0}
input,select,button {font:inherit;padding:.45rem;margin:.2rem}
button {cursor:pointer} button:disabled {opacity:.5;cursor:not-allowed}
pre {white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#8882;max-height:22rem;overflow:auto}
code {overflow-wrap:anywhere} .muted {opacity:.8}
fieldset {border:1px solid #aaa7;border-radius:6px}
#status {font-weight:600} #queue button {display:block;text-align:left;width:100%}
</style>
</head>
<body>
<header><h1>Nexus AI — Financial Evidence Review</h1>
<p class="muted">This workbench does not verify accounting rows automatically. Inspect the original PDF independently before recording a review decision.</p>
<label>Short-lived reviewer bearer token
<input id="token" type="password" autocomplete="off" spellcheck="false" size="66"></label>
<button id="connect">Use token in this tab only</button>
<button id="disconnect">Clear session</button>
<p id="status" role="status">Not connected.</p>
</header>
<section><h2>Pending review queue</h2>
<button id="refresh">Refresh</button><div id="queue"></div></section>
<section><h2>Selected evidence</h2>
<p id="metadata">Select a pending item.</p>
<pre id="excerpt" aria-label="Indexed source text">No evidence selected.</pre>
<p class="muted">Indexed source text is not a PDF rendering and cannot prove year, metric, or units. Open the original file and inspect the cited page.</p>
<button id="pdf">Download verified original PDF</button>
</section>
<section><h2>Explicit decision</h2>
<p>Before approval, visually inspect the original document and independently verify each accounting field.</p>
<form id="decision">
<label>Company <input id="company" required maxlength="160"></label>
<label>Financial year <input id="year" type="number" min="1900" max="2100" required></label>
<label>Metric <select id="metric">
<option value="revenue">Revenue</option><option value="net_income">Net income</option>
<option value="operating_income">Operating income</option><option value="assets">Assets</option>
<option value="liabilities">Liabilities</option><option value="equity">Equity</option>
<option value="cash_flow">Cash flow</option></select></label>
<label>Currency <select id="currency">
<option>SAR</option><option>USD</option><option>EUR</option><option>GBP</option>
<option>JOD</option><option>AED</option><option>QAR</option></select></label>
<label>Unit <select id="unit"><option>ones</option><option>thousands</option>
<option>millions</option><option>billions</option></select></label>
<fieldset><legend>Mandatory independent review</legend>
<label><input id="pageChecked" type="checkbox"> I visually inspected the original PDF page.</label>
<label><input id="rowChecked" type="checkbox"> I confirmed the metric, financial year, currency, and unit against the visible row.</label>
</fieldset>
<button type="submit" id="approve" disabled>Approve reviewed figure</button>
<button type="button" id="reject" disabled>Reject selection</button>
</form>
</section>
<script nonce="__NONCE__">
"use strict";
(function () {
  const el = id => document.getElementById(id);
  let token = "";
  let selected = null;
  const message = msg => { el("status").textContent = String(msg); };
  const clearSelection = () => {
    selected = null;
    el("metadata").textContent = "Select a pending item.";
    el("excerpt").textContent = "No evidence selected.";
    el("approve").disabled = true;
    el("reject").disabled = true;
    el("pageChecked").checked = false;
    el("rowChecked").checked = false;
    el("company").value = "";
    el("year").value = "";
  };
  async function request(path, method, payload, binary) {
    if (!token) { throw Error("Enter your reviewer token first."); }
    const options = {method: method || "GET", headers: {"Authorization": "Bearer " + token}, cache: "no-store"};
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const res = await fetch("/financial-reviews/" + path, options);
    if (!res.ok) { throw Error("Request failed (" + res.status + ")."); }
    if (binary) { return await res.blob(); }
    if (res.status === 204) { return null; }
    return await res.json();
  }
  async function refresh() {
    clearSelection();
    const data = await request("selections?limit=50");
    el("queue").replaceChildren();
    for (const row of data.items) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Item " + row.id + " — " + row.document_id + " · page " + row.page_number + " · " + row.amount;
      b.addEventListener("click", async () => {
        try {
          clearSelection();
          const info = await request("selections/" + row.id + "/evidence");
          selected = row.id;
          el("metadata").textContent = "Document: " + info.document_id + " | Version: " + info.version_id + " | Page: " + info.page_number + " | Number: " + info.amount;
          el("excerpt").textContent = info.indexed_excerpt;
          el("approve").disabled = false;
          el("reject").disabled = false;
          message("Indexed excerpt loaded. Original PDF still requires inspection.");
        } catch (e) { message(e.message); }
      });
      el("queue").appendChild(b);
    }
    message("Loaded " + data.items.length + " pending items.");
  }
  el("connect").addEventListener("click", async () => {
    token = el("token").value.trim();
    el("token").value = "";
    try { await refresh(); } catch (e) { message(e.message); }
  });
  el("disconnect").addEventListener("click", () => {
    token = "";
    el("token").value = "";
    el("queue").replaceChildren();
    clearSelection();
    message("Reviewer token cleared.");
  });
  el("refresh").addEventListener("click", async () => {
    try { await refresh(); } catch (e) { message(e.message); }
  });
  el("pdf").addEventListener("click", async () => {
    if (selected === null) { message("Select an item first."); return; }
    try {
      const blob = await request("selections/" + selected + "/original-pdf", "GET", undefined, true);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "financial-source.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      message("Original PDF download requested. Inspect the cited page manually.");
    } catch (e) { message(e.message); }
  });
  el("decision").addEventListener("submit", async evt => {
    evt.preventDefault();
    if (selected === null) { message("Select an item first."); return; }
    if (!el("pageChecked").checked || !el("rowChecked").checked) {
      message("Both independent visual attestations are required."); return;
    }
    const payload = {
      company: el("company").value.trim(),
      year: Number(el("year").value), metric: el("metric").value,
      currency: el("currency").value, unit: el("unit").value,
      source_page_visually_checked: true,
      metric_year_unit_visually_confirmed: true
    };
    try {
      await request("selections/" + selected + "/approve", "POST", payload);
      await refresh();
      message("Review decision recorded.");
    } catch (e) { message(e.message); }
  });
  el("reject").addEventListener("click", async () => {
    if (selected === null) { return; }
    if (!confirm("Reject this pending selection?")) { return; }
    try {
      await request("selections/" + selected + "/reject", "POST");
      await refresh();
      message("Selection rejected.");
    } catch (e) { message(e.message); }
  });
  window.addEventListener("pagehide", () => { token = ""; });
})();
</script>
</body></html>"""


def review_page_response() -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    return HTMLResponse(
        _PAGE.replace("__NONCE__", nonce),
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; base-uri 'none'; object-src 'none'; "
                "form-action 'self'; frame-ancestors 'none'; connect-src 'self'; "
                "style-src 'unsafe-inline'; script-src 'nonce-" + nonce + "'"
            ),
        },
    )
