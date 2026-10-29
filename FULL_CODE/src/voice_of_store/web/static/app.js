"use strict";
const $ = (id) => document.getElementById(id);
function el(tag, props, ...kids) {            // builds DOM with textContent only: feedback text can never become markup
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) { if (k === "class") n.className = v; else n.setAttribute(k, v); }
  for (const k of kids) n.append(k && k.nodeType ? k : document.createTextNode(String(k)));
  return n;
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({credentials: "omit", cache: "no-store"}, opts));
  if (!r.ok) throw new Error("request failed (" + r.status + ")");
  return r.json();
}
function fill(sel, items, label) { sel.replaceChildren(...items.map((x) => { const o = el("option", {value: x}, label ? label(x) : x); return o; })); }
let META = null;
function storeLabel(id) { const s = META.stores.find((x) => x.id === id); return s.name + " (" + s.region + ")"; }
const GREETING = "Hello. Ask me about a store, a region, emerging issues, who owns an issue, or the escalation rule. Press the up arrow to repeat an earlier question.";
const HISTORY = [];            // questions asked in this tab, for the up/down arrow recall
let hpos = 0;

function seriesSvg(s) {
  const w = 520, h = 90, n = s.weeks.length, bw = w / n;
  const max = Math.max(1, ...s.store_counts);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + w + " " + h); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Weekly reports of this issue at this store");
  s.store_counts.forEach((c, i) => {
    const r = document.createElementNS(svg.namespaceURI, "rect");
    const bh = (c / max) * (h - 14);
    r.setAttribute("x", i * bw + 1); r.setAttribute("y", h - bh - 12); r.setAttribute("width", Math.max(1, bw - 2)); r.setAttribute("height", bh);
    r.setAttribute("class", s.flagged_weeks.includes(s.weeks[i]) ? "flag" : "barS");
    const t = document.createElementNS(svg.namespaceURI, "title"); t.textContent = s.weeks[i] + ": " + c; r.append(t); svg.append(r);
  });
  return svg;
}

let briefSeq = 0;
async function showBrief() {
  const mine = ++briefSeq;
  const region = $("region").value, week = $("week").value;
  $("print").href = "/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week);
  const d = await api("/api/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week));
  if (mine !== briefSeq) return;
  const box = $("brief");
  if (!d.entries.length) { box.replaceChildren(el("p", {}, "No actionable issues this week.")); return; }
  box.replaceChildren(...d.entries.map((e, i) => el("section", {class: "card sev-" + e.severity},
    el("h2", {}, (i + 1) + ". " + e.issue + (e.beyond_top5 ? " (safety escalation, shown beyond the top 5)" : ""), el("span", {class: "trend", title: "vs last week"}, e.trend)),
    el("div", {class: "meta"}, el("b", {}, e.owner), " · severity ", el("b", {}, e.severity), " · ", e.tier, " · act: ", e.window),
    el("div", {class: "meta"}, e.count + " reports in " + e.dedup.incidents + " incident(s), " + e.dedup.cross_channel +
       " seen in 2+ channels (" + e.prev_count + " last week) · " + e.n_stores + " store(s): " + e.stores.map((s) => s[0] + " (" + s[1] + ")").join(", ")),
    el("div", {class: "meta"}, e.status + " Confidence score " + e.confidence + " · channels: " + e.by_channel.map((c) => c[0] + " " + c[1]).join(", ") +
       " · first " + e.first_seen + ", latest " + e.last_seen),
    el("div", {class: "meta"}, "Per 10,000 weekly visits: " + (Object.entries(e.rates).filter((x) => x[1] !== null).map((x) => x[0] + " " + x[1]).join(", ") || "not available")),
    e.emerging.length ? el("div", {class: "em"}, "Emerging at: " + e.emerging.join(", ")) : "",
    el("ul", {}, ...e.quotes.map((q) => el("li", {}, el("span", {class: "ch"}, q[0] + " · " + q[2]), "“" + q[1] + "”"))),
    el("div", {class: "next"}, el("b", {}, "Next step: "), e.next_step))));
}

async function showFlags() {
  $("export").href = "/api/export?week=" + encodeURIComponent($("eweek").value);
  const d = await api("/api/flags?week=" + encodeURIComponent($("eweek").value));
  const box = $("flags");
  if (!d.flags.length) { box.replaceChildren(el("p", {}, "No emerging-issue flags this week.")); return; }
  const cards = [];
  for (const f of d.flags) {
    const s = await api("/api/series?store_id=" + encodeURIComponent(f.store_id) + "&issue_type=" + encodeURIComponent(f.issue_type));
    cards.push(el("section", {class: "card sev-high"},
      el("h2", {}, f.issue + " at " + f.store),
      el("div", {class: "meta"}, f.owner + " · " + (f.region || "") + " · confidence " + f.confidence + " · review within 48 hours" + (f.owner_window === "same day" ? " (safety type: same day)" : "")),
      el("div", {class: "em"}, "What changed: " + f.change.summary),
      el("div", {class: "meta"}, f.status),
      seriesSvg(s), el("div", {class: "meta"}, "Bars: reports per week at this store (red = flagged week)."),
      el("ul", {}, ...f.evidence.map((q) => el("li", {}, el("span", {class: "ch"}, q.channel), "“" + q.text + "”"))),
      el("div", {class: "next"}, el("b", {}, "Next step: "), f.next_step)));
  }
  box.replaceChildren(...cards);
}

async function showPrecision() {
  const v = await api("/api/validation");
  const pct = (x) => (x * 100).toFixed(1) + "%";
  const ci = (c) => c ? " (95% interval " + pct(c[0]) + " to " + pct(c[1]) + ")" : "";
  $("precision").replaceChildren(
    el("h2", {}, "Precision statement (out of sample, forward in time)"),
    el("p", {}, "Of " + v.n_pred_actionable + " records marked actionable, " + pct(v.precision_actionable) + " truly were" + ci(v.ci_actionable) + "."),
    el("p", {}, "Of " + v.n_pred_actionable_high + " marked actionable and high or critical, " + pct(v.precision_actionable_high) + " were truly actionable" + ci(v.ci_actionable_high) + "."),
    el("table", {},
      el("tr", {}, el("th", {}, "Metric"), el("th", {}, "Value")),
      el("tr", {}, el("td", {}, "Issue macro-F1"), el("td", {}, v.issue_macro_f1.toFixed(3))),
      el("tr", {}, el("td", {}, "Severity weighted-F1"), el("td", {}, v.severity_weighted_f1.toFixed(3))),
      el("tr", {}, el("td", {}, "Actionable F1"), el("td", {}, v.actionable_f1.toFixed(3))),
      el("tr", {}, el("td", {}, "Classification score"), el("td", {}, v.classification.toFixed(3)))),
    el("p", {class: "sub"}, "Trained on labelled rows of weeks 1-9, tested on labelled rows of weeks 10-13. The labelled sample over-represents rare issue types, so these describe the sample, not the whole stream. Feedback is unverified."));
}

function weekBars(weeks, values, flagged) {
  const w = 520, h = 80, n = weeks.length, bw = w / n, max = Math.max(1, ...values);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + w + " " + h); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Actionable reports per week at this store");
  values.forEach((c, i) => {
    const r = document.createElementNS(svg.namespaceURI, "rect"), bh = (c / max) * (h - 14);
    r.setAttribute("x", i * bw + 1); r.setAttribute("y", h - bh - 12); r.setAttribute("width", Math.max(1, bw - 2)); r.setAttribute("height", bh);
    r.setAttribute("class", flagged.includes(weeks[i]) ? "flag" : "barS");
    const t = document.createElementNS(svg.namespaceURI, "title"); t.textContent = weeks[i] + ": " + c; r.append(t); svg.append(r);
  });
  return svg;
}

let storeSeq = 0;
async function showStore() {
  const mine = ++storeSeq;                      // latest request wins: a slow earlier response must not overwrite a newer one
  const o = await api("/api/store?store_id=" + encodeURIComponent($("store").value) + "&week=" + encodeURIComponent($("sweek").value));
  if (mine !== storeSeq) return;
  const flagged = o.flag_history.map((f) => f.week);
  const cards = o.top.map((t) => el("section", {class: "card sev-" + t.severity},
    el("h2", {}, t.issue, el("span", {class: "trend"}, t.trend)),
    el("div", {class: "meta"}, el("b", {}, t.owner), " · severity ", el("b", {}, t.severity), " · " + t.count + " reports (" + t.previous + " last week)"),
    el("ul", {}, ...t.quotes.map((q) => el("li", {}, "“" + q + "”"))),
    el("div", {class: "next"}, el("b", {}, "Next step: "), t.next_step)));
  $("storeview").replaceChildren(
    el("h2", {}, o.name + " · " + o.region),
    el("div", {class: "meta"}, o.reports_this_week + " actionable reports this week, " + o.reports_previous_week + " the week before"),
    weekBars(o.weeks, o.weekly_reports, flagged),
    el("div", {class: "meta"}, "Bars: actionable reports per week (red = a week with an emerging-issue flag at this store)."),
    o.flags_this_week.length ? el("div", {class: "em"}, "Emerging this week: " + o.flags_this_week.map((f) => f.issue).join(", ")) : "",
    ...(cards.length ? cards : [el("p", {}, "No actionable issues this week.")]),
    o.flag_history.length ? el("div", {class: "meta"}, "Flag history: " + o.flag_history.map((f) => f.week + " " + f.issue).join(" · ")) : "");
}

function say(role, text, items) {
  const box = el("div", {class: "msg " + role}, el("div", {}, text));
  (items || []).forEach((it) => box.append(el("div", {class: "item"}, el("b", {}, it.title), ...it.lines.map((l) => el("div", {class: "meta"}, l)))));
  $("chat").append(box); $("chat").scrollTop = $("chat").scrollHeight; return box;
}

async function ask(message) {
  HISTORY.push(message); hpos = HISTORY.length;
  say("me", message);
  const wait = say("bot", "…"); wait.setAttribute("aria-busy", "true");
  try {
    const r = await api("/api/assistant", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({message})});
    wait.remove();
    const box = say("bot", r.reply, r.items);
    if (r.source) box.append(el("div", {class: "meta"}, "Source: " + r.source + (r.week ? ", week of " + r.week : "")));
  } catch (e) { wait.remove(); say("bot", "That did not work (" + e.message + "). Please try again in a moment."); }
}

function setupAsk(suggestions) {
  $("chips").replaceChildren(...suggestions.map((s) => { const b = el("button", {type: "button", class: "chip"}, s); b.addEventListener("click", () => ask(s)); return b; }));
  $("askform").addEventListener("submit", (ev) => { ev.preventDefault(); const q = $("question").value.trim(); if (q) { $("question").value = ""; ask(q); } });
  $("clearchat").addEventListener("click", () => { $("chat").replaceChildren(); say("bot", GREETING); $("question").focus(); });
  $("question").addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowUp" && ev.key !== "ArrowDown") return;
    ev.preventDefault();
    hpos = Math.min(HISTORY.length, Math.max(0, hpos + (ev.key === "ArrowUp" ? -1 : 1)));
    $("question").value = HISTORY[hpos] || "";
  });
  say("bot", GREETING);
}

async function init() {
  META = await api("/api/meta");
  fill($("region"), META.regions); fill($("week"), META.test_weeks); fill($("eweek"), META.test_weeks);
  fill($("store"), META.stores.map((s) => s.id), storeLabel);
  fill($("sweek"), META.weeks); $("sweek").value = META.weeks[META.weeks.length - 1];
  $("storefilter").addEventListener("input", () => {
    const q = $("storefilter").value.trim().toLowerCase();
    const hit = META.stores.filter((s) => !q || (s.name + " " + s.region).toLowerCase().includes(q));
    fill($("store"), hit.map((s) => s.id), storeLabel);
    if (hit.length) showStore().catch(showErr);
  });
  $("store").addEventListener("change", () => showStore().catch(showErr)); $("sweek").addEventListener("change", () => showStore().catch(showErr));
  setupAsk(["What are the top issues in the South region this week?", "Any emerging issues this week?", "How is Kothrud doing?", "Who handles refrigeration problems?", "What is the escalation rule?", "How accurate is this?"]);
  fill($("channel"), META.channels); $("week").value = META.test_weeks[META.test_weeks.length - 1]; $("eweek").value = $("week").value;
  $("rule").textContent = META.escalation_rule;
  $("region").addEventListener("change", showBrief); $("week").addEventListener("change", showBrief); $("eweek").addEventListener("change", showFlags);
  const tabs = [...document.querySelectorAll("nav button")];
  const select = (b) => {
    tabs.forEach((x) => { x.setAttribute("aria-selected", x === b ? "true" : "false"); x.tabIndex = x === b ? 0 : -1; });
    for (const v of ["brief", "emerging", "stores", "ask", "try", "precision"]) $("view-" + v).hidden = v !== b.dataset.view;
    if (b.dataset.view === "emerging") showFlags().catch(showErr);
    if (b.dataset.view === "precision") showPrecision().catch(showErr);
    if (b.dataset.view === "stores") showStore().catch(showErr);
    if (b.dataset.view === "ask") $("question").focus();
  };
  tabs.forEach((b, i) => {
    b.addEventListener("click", () => select(b));
    b.addEventListener("keydown", (ev) => {           // arrow keys move between tabs (WAI-ARIA tabs pattern)
      const step = {ArrowRight: 1, ArrowLeft: -1}[ev.key];
      if (ev.key === "Home" || ev.key === "End" || step) {
        ev.preventDefault();
        const j = ev.key === "Home" ? 0 : ev.key === "End" ? tabs.length - 1 : (i + step + tabs.length) % tabs.length;
        tabs[j].focus(); select(tabs[j]);
      }
    });
  });
  $("tryform").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("/api/classify", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: $("text").value, channel: $("channel").value})});
      $("result").replaceChildren(el("section", {class: "card sev-" + r.severity},
        el("h2", {}, r.issue_type + " · " + r.issue),
        el("div", {class: "meta"}, "owner " + r.owner + " · severity " + r.severity + " · actionable " + (r.actionable ? "yes" : "no") + " · confidence score " + r.confidence),
        r.store_named ? el("div", {class: "meta"}, "store named in text: " + r.store_named) : "",
        r.note ? el("div", {class: "meta"}, r.note) : "",
        el("div", {class: "meta"}, "other candidates: " + r.alternatives.map((a) => a.issue_type + " " + a.score).join(", ")),
        el("div", {}, ...r.key_terms.map((t) => el("span", {class: "tag"}, t.term)))));
    } catch (e) { showErr(e); }
  });
  await showBrief();
}
function showErr(e) { $("rule").textContent = "Something went wrong: " + e.message; }
init().catch(showErr);
