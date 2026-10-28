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

async function showBrief() {
  const region = $("region").value, week = $("week").value;
  $("print").href = "/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week);
  const d = await api("/api/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week));
  const box = $("brief");
  if (!d.entries.length) { box.replaceChildren(el("p", {}, "No actionable issues this week.")); return; }
  box.replaceChildren(...d.entries.map((e, i) => el("section", {class: "card sev-" + e.severity},
    el("h2", {}, (i + 1) + ". " + e.issue, el("span", {class: "trend", title: "vs last week"}, e.trend)),
    el("div", {class: "meta"}, el("b", {}, e.owner), " · severity ", el("b", {}, e.severity), " · ", e.tier, " · act: ", e.window),
    el("div", {class: "meta"}, e.count + " reports in " + e.dedup.incidents + " incident(s), " + e.dedup.cross_channel +
       " seen in 2+ channels (" + e.prev_count + " last week) · " + e.n_stores + " store(s): " + e.stores.map((s) => s[0] + " (" + s[1] + ")").join(", ")),
    e.emerging.length ? el("div", {class: "em"}, "Emerging at: " + e.emerging.join(", ")) : "",
    el("ul", {}, ...e.quotes.map((q) => el("li", {}, el("span", {class: "ch"}, q[0]), "“" + q[1] + "”"))))));
}

async function showFlags() {
  const d = await api("/api/flags?week=" + encodeURIComponent($("eweek").value));
  const box = $("flags");
  if (!d.flags.length) { box.replaceChildren(el("p", {}, "No emerging-issue flags this week.")); return; }
  const cards = [];
  for (const f of d.flags) {
    const s = await api("/api/series?store_id=" + encodeURIComponent(f.store_id) + "&issue_type=" + encodeURIComponent(f.issue_type));
    cards.push(el("section", {class: "card sev-high"},
      el("h2", {}, f.issue + " at " + f.store),
      el("div", {class: "meta"}, f.owner + " · " + (f.region || "") + " · confidence " + f.confidence + " · review within 48 hours"),
      seriesSvg(s), el("div", {class: "meta"}, "Bars: reports per week at this store (red = flagged week)."),
      el("ul", {}, ...f.evidence.map((q) => el("li", {}, el("span", {class: "ch"}, q.channel), "“" + q.text + "”")))));
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

async function init() {
  META = await api("/api/meta");
  fill($("region"), META.regions); fill($("week"), META.test_weeks); fill($("eweek"), META.test_weeks);
  fill($("channel"), META.channels); $("week").value = META.test_weeks[META.test_weeks.length - 1]; $("eweek").value = $("week").value;
  $("rule").textContent = META.escalation_rule;
  $("region").addEventListener("change", showBrief); $("week").addEventListener("change", showBrief); $("eweek").addEventListener("change", showFlags);
  document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((x) => x.setAttribute("aria-selected", x === b ? "true" : "false"));
    for (const v of ["brief", "emerging", "try", "precision"]) $("view-" + v).hidden = v !== b.dataset.view;
    if (b.dataset.view === "emerging") showFlags().catch(showErr);
    if (b.dataset.view === "precision") showPrecision().catch(showErr);
  }));
  $("tryform").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("/api/classify", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: $("text").value, channel: $("channel").value})});
      $("result").replaceChildren(el("section", {class: "card sev-" + r.severity},
        el("h2", {}, r.issue_type + " · " + r.issue),
        el("div", {class: "meta"}, "owner " + r.owner + " · severity " + r.severity + " · actionable " + (r.actionable ? "yes" : "no") + " · confidence " + r.confidence),
        r.store_named ? el("div", {class: "meta"}, "store named in text: " + r.store_named) : "",
        r.note ? el("div", {class: "meta"}, r.note) : "",
        el("div", {class: "meta"}, "other candidates: " + r.alternatives.map((a) => a.issue_type + " " + a.probability).join(", ")),
        el("div", {}, ...r.key_terms.map((t) => el("span", {class: "tag"}, t.term)))));
    } catch (e) { showErr(e); }
  });
  await showBrief();
}
function showErr(e) { $("rule").textContent = "Something went wrong: " + e.message; }
init().catch(showErr);
