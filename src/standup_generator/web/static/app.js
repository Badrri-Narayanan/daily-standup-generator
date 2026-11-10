"use strict";

const $ = (id) => document.getElementById(id);
let currentId = null;

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key) || "";
    localStorage.setItem(key, value);
  } catch (_) {
    return "";
  }
}

function fmt(iso) {
  return iso ? iso.slice(0, 16).replace("T", " ") : "";
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(`${res.status} ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

async function loadWindow() {
  const since = $("since").value;
  try {
    const w = await api("GET", "/api/window" + (since ? `?since=${since}` : ""));
    $("window-label").textContent = `Covering ${fmt(w.start)} → now`;
  } catch (e) {
    $("window-label").textContent = `Could not compute window: ${e.message}`;
  }
}

function showErrors(errors) {
  const box = $("errors");
  box.replaceChildren();
  for (const [source, list] of Object.entries(errors || {})) {
    for (const msg of list) {
      const div = document.createElement("div");
      div.className = "banner";
      div.textContent = msg.startsWith(source) ? msg : `${source}: ${msg}`;
      box.appendChild(div);
    }
  }
}

function showResult({ id, prompt, windowStart, windowEnd, finalText, collected }) {
  currentId = id;
  $("result").classList.remove("hidden");
  $("prompt").value = prompt;
  $("final").value = finalText || "";
  $("final-status").textContent = "";
  $("result-meta").textContent = `${fmt(windowStart)} → ${fmt(windowEnd)}${id ? ` · #${id}` : ""}`;
  $("save-final").disabled = !id;
  const c = collected || {};
  const n = (k) => (c[k] || []).length;
  $("counts").textContent =
    `(${n("in_progress")} in progress, ${n("completed")} completed, ` +
    `${n("other_tickets") + n("other_commits") + n("other_prs")} other, ${n("blocker_hints")} possible blockers)`;
  $("collected").textContent = JSON.stringify(c, null, 2);
}

async function onGenerate() {
  const btn = $("generate");
  btn.disabled = true;
  $("status").textContent = "Collecting from Jira, GitHub and git…";
  try {
    const body = { plans: $("plans").value, blockers: $("blockers").value, since: $("since").value || null };
    const r = await api("POST", "/api/generate", body);
    showErrors(r.errors);
    showResult({ id: r.id, prompt: r.prompt, windowStart: r.window.start, windowEnd: r.window.end, collected: r.collected });
    $("status").textContent = "Done.";
    store("standup.plans", "");
    store("standup.blockers", "");
    loadHistory();
  } catch (e) {
    $("status").textContent = `Failed: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function onCopy() {
  try {
    await navigator.clipboard.writeText($("prompt").value);
    $("copy").textContent = "Copied ✓";
  } catch (_) {
    $("prompt").select();
    document.execCommand("copy");
    $("copy").textContent = "Copied";
  }
  setTimeout(() => ($("copy").textContent = "Copy prompt"), 1500);
}

async function onSaveFinal() {
  if (!currentId) return;
  try {
    await api("PATCH", `/api/history/${currentId}`, { final_standup: $("final").value });
    $("final-status").textContent = "Saved.";
    loadHistory();
  } catch (e) {
    $("final-status").textContent = `Failed: ${e.message}`;
  }
}

async function openEntry(id) {
  try {
    const e = await api("GET", `/api/history/${id}`);
    showErrors(e.source_errors);
    showResult({ id: e.id, prompt: e.prompt, windowStart: e.window_start, windowEnd: e.window_end,
                 finalText: e.final_standup, collected: e.collected });
    $("result").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    alert(`Could not load entry: ${err.message}`);
  }
}

async function deleteEntry(id) {
  if (!confirm(`Delete history entry #${id}?`)) return;
  try {
    await api("DELETE", `/api/history/${id}`);
    if (currentId === id) {
      currentId = null;
      $("result").classList.add("hidden");
    }
    loadHistory();
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}

async function loadHistory() {
  const list = $("history");
  let rows = [];
  try {
    rows = await api("GET", "/api/history");
  } catch (e) {
    list.replaceChildren();
    $("history-empty").textContent = e.message.includes("history disabled") ? "History is disabled." : e.message;
    $("history-empty").classList.remove("hidden");
    return;
  }
  list.replaceChildren();
  $("history-empty").textContent = "No standups yet.";
  $("history-empty").classList.toggle("hidden", rows.length > 0);
  for (const r of rows) {
    const li = document.createElement("li");
    const open = document.createElement("button");
    open.className = "open";
    const title = document.createElement("span");
    title.innerHTML = r.has_final ? '<span class="done">✓</span> ' : "";
    title.append(`#${r.id} · ${fmt(r.created_at)} · covers ${r.window_start.slice(0, 10)}`);
    const preview = document.createElement("span");
    preview.className = "preview";
    preview.textContent = r.preview || (r.has_final ? "" : "No final standup saved");
    open.append(title, preview);
    open.addEventListener("click", () => openEntry(r.id));
    const del = document.createElement("button");
    del.className = "link danger";
    del.textContent = "Delete";
    del.addEventListener("click", () => deleteEntry(r.id));
    li.append(open, del);
    list.appendChild(li);
  }
}

for (const id of ["plans", "blockers"]) {
  $(id).value = store(`standup.${id}`);
  $(id).addEventListener("input", () => store(`standup.${id}`, $(id).value));
}
$("since").addEventListener("change", loadWindow);
$("generate").addEventListener("click", onGenerate);
$("copy").addEventListener("click", onCopy);
$("save-final").addEventListener("click", onSaveFinal);
$("refresh-history").addEventListener("click", loadHistory);

loadWindow();
loadHistory();
