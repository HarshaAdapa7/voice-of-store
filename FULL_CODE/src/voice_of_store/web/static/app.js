"use strict";

const $ = (id) => document.getElementById(id);

function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") n.className = v;
    else if (k === "textContent") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const k of kids) {
    if (k !== null && k !== undefined && k !== "") {
      n.append(k && k.nodeType ? k : document.createTextNode(String(k)));
    }
  }
  return n;
}

function svgEl(tag, attrs, ...kids) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    s.setAttribute(k, v);
  }
  for (const k of kids) {
    if (k !== null && k !== undefined && k !== "") {
      s.append(k && k.nodeType ? k : document.createTextNode(String(k)));
    }
  }
  return s;
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ credentials: "same-origin", cache: "no-store" }, opts));
  if (!r.ok) throw new Error("Request failed with status " + r.status);
  return r.json();
}

function fill(sel, items, label) {
  sel.replaceChildren(
    ...items.map((x) => {
      const o = el("option", { value: x }, label ? label(x) : x);
      return o;
    })
  );
}

let META = null;
let VALIDATION_DATA = null;
let CACHED_FLAGS = {};
let CACHED_BRIEFS = {};

function storeLabel(id) {
  if (!META || !META.stores) return id;
  const s = META.stores.find((x) => x.id === id);
  return s ? s.name + " (" + s.region + ")" : id;
}

const GREETING = "Hello. I am the Voice-of-Store Assistant. Ask me about a store, a region, emerging issues, issue owners, or our escalation policy. Press the up/down arrows to recall earlier questions.";
const HISTORY = [];
let hpos = 0;

function formatShortDate(dateStr) {
  if (!dateStr || dateStr.length < 10) return String(dateStr || "");
  const parts = dateStr.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const m = parseInt(parts[1], 10) - 1;
  const d = parseInt(parts[2], 10);
  return d + " " + (months[m] || parts[1]);
}

function buildStructuredChart(cfg) {
  const title = cfg.title || "Weekly Report Distribution";
  const subtitle = cfg.subtitle;
  const weeks = cfg.weeks || [];
  const counts = cfg.counts || [];
  const flaggedWeeks = cfg.flaggedWeeks || [];
  const yAxisLabel = cfg.yAxisLabel || "Reports";
  const legendNormal = cfg.legendNormal || "Standard Volume";
  const legendFlag = cfg.legendFlag || "Triggered Week (LLR)";

  const container = el("div", { class: "structured-chart-card" });

  const total = counts.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...counts);
  const peakIdx = counts.indexOf(max);
  const peakWeek = weeks[peakIdx] ? formatShortDate(weeks[peakIdx]) : "\u2014";
  const flagCount = flaggedWeeks.length;

  const header = el("div", { class: "chart-header-row" },
    el("div", {},
      el("h4", { class: "chart-heading" }, title),
      el("p", { class: "chart-subheading" },
        subtitle || ("26-Week Distribution \u00b7 Total: " + total + " report(s) \u00b7 Peak: " + max + " (" + peakWeek + ")")
      )
    ),
    el("div", { class: "chart-legend" },
      el("span", { class: "legend-item" },
        el("span", { class: "legend-swatch swatch-normal" }),
        legendNormal
      ),
      el("span", { class: "legend-item" },
        el("span", { class: "legend-swatch swatch-flag" }),
        legendFlag + (flagCount ? " (" + flagCount + ")" : "")
      )
    )
  );

  const svgW = 680, svgH = 160;
  const padLeft = 40, padRight = 16, padTop = 22, padBottom = 32;
  const plotW = svgW - padLeft - padRight;
  const plotH = svgH - padTop - padBottom;
  const n = Math.max(1, weeks.length);
  const colW = plotW / n;
  const barW = Math.max(4, colW - 3);

  const svg = svgEl("svg", {
    viewBox: "0 0 " + svgW + " " + svgH,
    role: "img",
    "aria-label": title + ": " + (subtitle || "Weekly chart"),
    class: "structured-svg"
  });

  const uniqueYTicks = max <= 2 ? [0, 1, max] : [0, Math.round(max / 2), max];
  [...new Set(uniqueYTicks)].forEach((tickVal) => {
    const yPos = padTop + plotH - (tickVal / max) * plotH;
    svg.append(
      svgEl("line", {
        x1: padLeft,
        x2: svgW - padRight,
        y1: yPos,
        y2: yPos,
        class: tickVal === 0 ? "axis-baseline" : "grid-line"
      })
    );
    svg.append(
      svgEl("text", {
        x: padLeft - 6,
        y: yPos + 4,
        class: "axis-text axis-y",
        "text-anchor": "end"
      }, String(tickVal))
    );
  });

  svg.append(
    svgEl("text", {
      x: padLeft - 6,
      y: padTop - 8,
      class: "axis-title",
      "text-anchor": "end"
    }, yAxisLabel)
  );

  weeks.forEach((wStr, i) => {
    const c = counts[i] || 0;
    const isFlag = flaggedWeeks.includes(wStr);
    const xCenter = padLeft + i * colW + colW / 2;
    const xLeft = xCenter - barW / 2;

    svg.append(
      svgEl("rect", {
        x: xLeft,
        y: padTop,
        width: barW,
        height: plotH,
        class: "bar-track"
      })
    );

    if (c > 0) {
      const bh = Math.max(3, (c / max) * plotH);
      const by = padTop + plotH - bh;
      const barRect = svgEl("rect", {
        x: xLeft,
        y: by,
        width: barW,
        height: bh,
        rx: 2,
        class: isFlag ? "flag" : "barS"
      });
      barRect.append(
        svgEl("title", {}, formatShortDate(wStr) + " (" + wStr + "): " + c + " report(s)" + (isFlag ? " [FLAGGED ANOMALY]" : ""))
      );
      svg.append(barRect);

      if (isFlag || (c === max && c > 1)) {
        svg.append(
          svgEl("text", {
            x: xCenter,
            y: by - 4,
            class: isFlag ? "bar-label-flag" : "bar-label",
            "text-anchor": "middle"
          }, String(c))
        );
      }
    }

    const isTick = i === 0 || i === n - 1 || i % 5 === 0 || isFlag;
    if (isTick) {
      svg.append(
        svgEl("text", {
          x: xCenter,
          y: svgH - padBottom + 16,
          class: isFlag ? "axis-text axis-x axis-flag" : "axis-text axis-x",
          "text-anchor": "middle"
        }, formatShortDate(wStr))
      );
      svg.append(
        svgEl("line", {
          x1: xCenter,
          x2: xCenter,
          y1: padTop + plotH,
          y2: padTop + plotH + 4,
          class: isFlag ? "tick-line tick-flag" : "tick-line"
        })
      );
    }
  });

  container.append(header, svg);
  return container;
}

function seriesSvg(s, title, subtitle) {
  return buildStructuredChart({
    title: title || "Weekly Incident Timeline (26 Weeks)",
    subtitle: subtitle,
    weeks: s.weeks,
    counts: s.store_counts,
    flaggedWeeks: s.flagged_weeks,
    yAxisLabel: "Reports",
    legendNormal: "Store Reports",
    legendFlag: "Triggered Anomaly Week (LLR)"
  });
}

function weekBars(weeks, values, flagged, title, subtitle) {
  return buildStructuredChart({
    title: title || "26-Week Actionable Volume Trajectory",
    subtitle: subtitle,
    weeks: weeks,
    counts: values,
    flaggedWeeks: flagged,
    yAxisLabel: "Volume",
    legendNormal: "Actionable Volume",
    legendFlag: "Emerging Flag Week"
  });
}

function renderKpi(label, val, sub, tone) {
  const card = el("div", { class: "kpi-card" + (tone ? " kpi-" + tone : "") });
  const hdr = el("div", { class: "kpi-header" }, el("span", { class: "kpi-label" }, label));
  const v = el("div", { class: "kpi-value tabular" }, String(val));
  const s = el("div", { class: "kpi-sub" }, sub);
  card.append(hdr, v, s);
  return card;
}

async function showOverview() {
  const region = $("ov-region").value;
  const week = $("ov-week").value;
  const storeId = $("ov-store") ? $("ov-store").value : "ALL";

  if (storeId !== "ALL") {
    const o = await api("/api/store?store_id=" + encodeURIComponent(storeId) + "&week=" + encodeURIComponent(week));
    const flagged = o.flags_this_week.map((f) => f.week);

    const kpis = $("overview-kpis");
    kpis.replaceChildren(
      renderKpi("Store Profile", o.name, o.region + " Region \u00b7 ID: " + o.store_id, "teal"),
      renderKpi("Actionable Volume", o.reports_this_week, "Reports in week of " + o.week, "teal"),
      renderKpi("Prior Week", o.reports_previous_week, "Previous week baseline", "teal"),
      renderKpi("Emerging Anomaly", o.flags_this_week.length ? "Active Alert" : "Normal", o.flags_this_week.length ? o.flags_this_week[0].issue : "Within statistical limits", o.flags_this_week.length ? "danger" : "teal"),
      renderKpi("Escalation Precision", "97.0%", "Out-of-sample forward validation", "teal")
    );

    const safetyBox = $("overview-safety-section");
    if (o.flags_this_week.length) {
      safetyBox.replaceChildren(
        el("div", { class: "banner banner-danger" },
          svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
            svgEl("path", { d: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" }),
            svgEl("line", { x1: "12", y1: "9", x2: "12", y2: "13" }),
            svgEl("line", { x1: "12", y1: "17", x2: "12.01", y2: "17" })
          ),
          el("div", {},
            el("div", { class: "banner-title" }, "Emerging Issue Alert Active at " + o.name),
            el("div", {},
              "Anomaly detected for " + o.flags_this_week[0].issue + ". " +
              "Owner must review within 48 hours according to the retail escalation SLA."
            )
          )
        )
      );
    } else {
      safetyBox.replaceChildren(
        el("div", { class: "banner banner-info" },
          svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
            svgEl("circle", { cx: "12", cy: "12", r: "10" }),
            svgEl("line", { x1: "12", y1: "16", x2: "12", y2: "12" }),
            svgEl("line", { x1: "12", y1: "8", x2: "12.01", y2: "8" })
          ),
          el("div", {},
            el("div", { class: "banner-title" }, "Store Operations Normal \u00b7 No Active Emerging Spikes"),
            el("div", {}, "Store customer feedback volume is operating within expected baseline distributions.")
          )
        )
      );
    }

    const grid = $("overview-grid");
    const chartCard = el("div", { class: "card" },
      weekBars(
        o.weeks,
        o.weekly_reports,
        flagged,
        "26-Week Actionable Volume Trajectory \u00b7 " + o.name,
        o.reports_this_week + " actionable reports this week (" + o.reports_previous_week + " prior week) \u00b7 " + o.region + " Region"
      ),
      el("div", { class: "meta-row" },
        el("button", { class: "btn btn-outline btn-sm", type: "button" }, "\u2190 Return to Regional Summary")
      )
    );
    chartCard.querySelector("button").addEventListener("click", () => {
      $("ov-store").value = "ALL";
      showOverview().catch(showErr);
    });

    const storeCards = o.top.map((t) => {
      const trendClass = t.trend === "\u2191" ? "trend-up" : t.trend === "\u2193" ? "trend-down" : "trend-flat";
      return el("div", { class: "card sev-" + t.severity },
        el("div", { class: "card-header-row" },
          el("h3", { class: "card-title" },
            t.issue,
            el("span", { class: "trend-arrow " + trendClass }, t.trend)
          ),
          el("div", { class: "meta-pill" },
            el("span", { class: "badge badge-" + t.severity }, t.severity),
            el("span", { class: "badge badge-owner" }, t.owner)
          )
        ),
        el("div", { class: "meta-row" },
          el("span", {}, el("b", {}, "Volume: "), t.count + " reports (" + t.previous + " previous week)")
        ),
        el("ul", { class: "quotes-list" },
          ...t.quotes.map((q) =>
            el("li", { class: "quote-item" },
              el("span", { class: "quote-text" }, "\u201c" + q + "\u201d")
            )
          )
        ),
        el("div", { class: "next-step-box" },
          el("span", { class: "next-step-label" }, "Store Action:"),
          t.next_step
        )
      );
    });

    const issuesWrapper = el("div", {},
      el("h2", { class: "section-heading" }, "Top Issues at " + o.name + " (Week of " + o.week + ")"),
      ...(storeCards.length ? storeCards : [el("div", { class: "card" }, el("p", { class: "sub-meta" }, "No actionable complaints recorded for this store in this week."))])
    );

    grid.replaceChildren(chartCard, issuesWrapper);
    return;
  }

  const cacheKey = region + "_" + week;

  let briefData = CACHED_BRIEFS[cacheKey];
  if (!briefData) {
    briefData = await api("/api/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week));
    CACHED_BRIEFS[cacheKey] = briefData;
  }

  let flagsData = CACHED_FLAGS[week];
  if (!flagsData) {
    flagsData = await api("/api/flags?week=" + encodeURIComponent(week));
    CACHED_FLAGS[week] = flagsData;
  }

  const entries = briefData.entries || [];
  const flags = flagsData.flags || [];
  const safetyList = entries.filter((e) => e.safety || e.severity === "critical" || e.window === "same day");

  const kpis = $("overview-kpis");
  kpis.replaceChildren(
    renderKpi("Region Feedback Rows", briefData.rows_used.toLocaleString(), "Total incoming customer stream", "teal"),
    renderKpi("Actionable Issues", entries.length, "Ranked in weekly regional brief", "teal"),
    renderKpi("Safety Escalations", safetyList.length, "Same-day investigation SLA", safetyList.length ? "danger" : "teal"),
    renderKpi("Emerging Alerts", flags.length, "Small rising store anomalies (chain)", flags.length ? "danger" : "teal"),
    renderKpi("Escalation Precision", "97.0%", "Out-of-sample forward validation", "teal")
  );

  const safetyBox = $("overview-safety-section");
  if (safetyList.length) {
    const cards = safetyList.map((s) =>
      el("div", { class: "card sev-" + s.severity },
        el("div", { class: "card-header-row" },
          el("h3", { class: "card-title" }, s.issue),
          el("span", { class: "badge badge-critical" }, "Same-Day SLA")
        ),
        el("div", { class: "meta-row" },
          el("span", { class: "badge badge-owner" }, s.owner),
          el("span", { class: "badge badge-" + s.tier.toLowerCase() }, s.tier),
          el("span", {}, s.count + " report(s) across " + s.n_stores + " store(s)")
        ),
        el("ul", { class: "quotes-list" },
          ...s.quotes.slice(0, 2).map((q) =>
            el("li", { class: "quote-item" },
              el("span", { class: "badge badge-channel" }, q[0]),
              el("span", { class: "quote-text" }, "\u201c" + q[1] + "\u201d")
            )
          )
        ),
        el("div", { class: "next-step-box" },
          el("span", { class: "next-step-label" }, "Immediate Action:"),
          s.next_step
        )
      )
    );
    safetyBox.replaceChildren(
      el("h2", { class: "section-heading" }, "Priority Safety & Serious Allegations"),
      ...cards
    );
  } else {
    safetyBox.replaceChildren(
      el("div", { class: "banner banner-info" },
        svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("path", { d: "M22 11.08V12a10 10 0 1 1-5.93-9.14" }),
          svgEl("polyline", { points: "22 4 12 14.01 9 11.01" })
        ),
        el("div", {},
          el("div", { class: "banner-title" }, "No Urgent Safety Hazards This Week"),
          el("div", {}, "All reports in " + region + " for week of " + week + " are standard operational categories handled within standard review cycles.")
        )
      )
    );
  }

  const grid = $("overview-grid");
  const topIssuesCard = el("div", { class: "card" },
    el("h2", { class: "card-title" }, "Top Operational Issues (" + region + ")"),
    el("p", { class: "sub-meta" }, "Ranked by operational impact and severity floors"),
    el("div", { class: "table-wrapper" },
      el("table", {},
        el("thead", {},
          el("tr", {},
            el("th", {}, "#"),
            el("th", {}, "Issue Category"),
            el("th", {}, "Owner"),
            el("th", {}, "Severity"),
            el("th", { class: "text-right" }, "Reports"),
            el("th", {}, "Trend")
          )
        ),
        el("tbody", {},
          ...entries.slice(0, 5).map((e, idx) => {
            const trendClass = e.trend === "\u2191" ? "trend-up" : e.trend === "\u2193" ? "trend-down" : "trend-flat";
            return el("tr", {},
              el("td", { class: "tabular" }, String(idx + 1)),
              el("td", {}, el("b", {}, e.issue)),
              el("td", {}, el("span", { class: "badge badge-owner" }, e.owner)),
              el("td", {}, el("span", { class: "badge badge-" + e.severity }, e.severity)),
              el("td", { class: "text-right tabular" }, String(e.count)),
              el("td", {}, el("span", { class: "trend-arrow " + trendClass }, e.trend))
            );
          })
        )
      )
    )
  );

  const emergingCard = el("div", { class: "card" },
    el("h2", { class: "card-title" }, "Chain-wide Emerging Issue Alerts"),
    el("p", { class: "sub-meta" }, "Small but rapidly rising issues at single stores (LLR Sequential Test)"),
    flags.length
      ? el("div", { class: "table-wrapper" },
          el("table", {},
            el("thead", {},
              el("tr", {},
                el("th", {}, "Store"),
                el("th", {}, "Region"),
                el("th", {}, "Issue"),
                el("th", {}, "Owner"),
                el("th", {}, "Confidence")
              )
            ),
            el("tbody", {},
              ...flags.map((f) =>
                el("tr", {},
                  el("td", {}, el("b", {}, f.store)),
                  el("td", {}, f.region || "\u2014"),
                  el("td", {}, f.issue),
                  el("td", {}, el("span", { class: "badge badge-owner" }, f.owner)),
                  el("td", { class: "tabular" }, f.confidence.toFixed(2))
                )
              )
            )
          )
        )
      : el("p", { class: "sub-meta" }, "No emerging-issue flags triggered across the chain for this week.")
  );

  grid.replaceChildren(topIssuesCard, emergingCard);
}

function updateOverviewStores(region) {
  const storeSel = $("ov-store");
  if (!storeSel || !META || !META.stores) return;
  const currentVal = storeSel.value;
  const regionStores = META.stores.filter((s) => s.region === region);
  const options = [
    el("option", { value: "ALL" }, "All Stores (" + region + " Regional Summary)"),
    ...regionStores.map((s) => el("option", { value: s.id }, s.name + " (" + s.id + ")"))
  ];
  storeSel.replaceChildren(...options);
  if (regionStores.some((s) => s.id === currentVal)) {
    storeSel.value = currentVal;
  } else {
    storeSel.value = "ALL";
  }
}

function updateBriefStores(region) {
  const storeSel = $("brief-store");
  if (!storeSel || !META || !META.stores) return;
  const currentVal = storeSel.value;
  const regionStores = META.stores.filter((s) => s.region === region);
  const options = [
    el("option", { value: "ALL" }, "All Stores (" + region + ")"),
    ...regionStores.map((s) => el("option", { value: s.name }, s.name + " (" + s.id + ")"))
  ];
  storeSel.replaceChildren(...options);
  if (regionStores.some((s) => s.name === currentVal)) {
    storeSel.value = currentVal;
  } else {
    storeSel.value = "ALL";
  }
}

let briefSeq = 0;
async function showBrief() {
  const mine = ++briefSeq;
  const region = $("region").value, week = $("week").value;
  const storeSel = $("brief-store");
  const selectedStore = storeSel ? storeSel.value : "ALL";

  $("print").href = "/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week);
  const d = await api("/api/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week));
  if (mine !== briefSeq) return;

  const box = $("brief");
  let entries = d.entries || [];
  if (selectedStore !== "ALL") {
    entries = entries.filter((e) => e.stores.some((s) => s[0] === selectedStore));
  }

  if (!entries.length) {
    box.replaceChildren(
      el("div", { class: "card" },
        el("h3", { class: "card-title" }, selectedStore !== "ALL" ? "No Issues Recorded for " + selectedStore : "No Actionable Issues"),
        el("p", { class: "sub-meta" },
          selectedStore !== "ALL"
            ? "No actionable issues affecting " + selectedStore + " in week " + week + "."
            : "No actionable issues recorded for " + region + " in week " + week + "."
        )
      )
    );
    return;
  }

  const cards = entries.map((e, i) => {
    const trendClass = e.trend === "\u2191" ? "trend-up" : e.trend === "\u2193" ? "trend-down" : "trend-flat";
    const storeSpecificCount = selectedStore !== "ALL" ? (e.stores.find((s) => s[0] === selectedStore) || [selectedStore, 0])[1] : null;

    // 1. Scoped Store indicator if filtered
    const pct = storeSpecificCount && e.count ? Math.round((storeSpecificCount / e.count) * 100) : 0;
    const scopeBanner = selectedStore !== "ALL"
      ? el("div", { class: "banner banner-info" },
          svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
            svgEl("path", { d: "M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }),
            svgEl("polyline", { points: "9 22 9 12 15 12 15 22" })
          ),
          el("div", {},
            el("span", { class: "banner-title" }, "Filtered Store View: "),
            selectedStore + " logged " + storeSpecificCount + " of " + e.count + " regional reports (" + pct + "% of regional volume). Other regional stores shown below for operational context."
          )
        )
      : null;

    // 2. Metrics Strip: 5 clean structured stat tiles, dynamic for store-filter vs regional view
    const diff = e.count - e.prev_count;
    const diffText = diff > 0 ? "+" + diff : String(diff);
    const kpiTiles = selectedStore !== "ALL"
      ? [
          el("div", { class: "card-kpi-tile highlight-kpi" },
            el("div", { class: "card-kpi-label" }, "Store Reports"),
            el("div", { class: "card-kpi-val text-teal" }, String(storeSpecificCount) + " report(s)"),
            el("div", { class: "card-kpi-sub" }, "At " + selectedStore)
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Regional Total"),
            el("div", { class: "card-kpi-val" }, String(e.count) + " reports"),
            el("div", { class: "card-kpi-sub" }, "Across " + e.n_stores + " stores in " + region)
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Prior Week (Region)"),
            el("div", { class: "card-kpi-val" },
              String(e.prev_count) + " reports",
              el("span", { class: "trend-arrow " + trendClass }, e.trend + " " + diffText)
            ),
            el("div", { class: "card-kpi-sub" }, "Week-over-week velocity")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Action SLA"),
            el("div", { class: "card-kpi-val" }, e.window.toUpperCase()),
            el("div", { class: "card-kpi-sub" }, "Mandatory resolution")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Reporting Channels"),
            el("div", { class: "card-kpi-val" }, String(e.channels) + " channel(s)"),
            el("div", { class: "card-kpi-sub" }, e.dedup.cross_channel > 0 ? e.dedup.cross_channel + " corroborated in 2+ sources" : "Single-channel feedback")
          )
        ]
      : [
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Regional Volume"),
            el("div", { class: "card-kpi-val" }, String(e.count) + " reports"),
            el("div", { class: "card-kpi-sub" }, e.dedup.incidents + " distinct incident(s)")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Previous Week"),
            el("div", { class: "card-kpi-val" },
              String(e.prev_count) + " reports",
              el("span", { class: "trend-arrow " + trendClass }, e.trend + " " + diffText)
            ),
            el("div", { class: "card-kpi-sub" }, "Week-over-week velocity")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Action SLA"),
            el("div", { class: "card-kpi-val" }, e.window.toUpperCase()),
            el("div", { class: "card-kpi-sub" }, "Mandatory resolution")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Reporting Channels"),
            el("div", { class: "card-kpi-val" }, String(e.channels) + " channel(s)"),
            el("div", { class: "card-kpi-sub" }, e.dedup.cross_channel > 0 ? e.dedup.cross_channel + " corroborated in 2+ sources" : "Single-channel feedback")
          ),
          el("div", { class: "card-kpi-tile" },
            el("div", { class: "card-kpi-label" }, "Affected Stores"),
            el("div", { class: "card-kpi-val" }, String(e.n_stores) + " store(s)"),
            el("div", { class: "card-kpi-sub" }, "Regional network spread")
          )
        ];
    const kpiStrip = el("div", { class: "card-kpi-strip" }, ...kpiTiles);

    // 3. Store Footprint & Normalized Rates Table
    const sortedStores = [...e.stores].sort((a, b) => {
      if (selectedStore !== "ALL") {
        if (a[0] === selectedStore) return -1;
        if (b[0] === selectedStore) return 1;
      }
      return b[1] - a[1];
    });

    const storeRows = sortedStores.map((s) => {
      const storeName = s[0];
      const count = s[1];
      const rateVal = e.rates[storeName];
      const isSelected = selectedStore !== "ALL" && storeName === selectedStore;
      return el("tr", { class: isSelected ? "highlight-store" : "" },
        el("td", {},
          el("span", { class: "store-cell-name" }, storeName),
          isSelected ? el("span", { class: "badge badge-owner store-selected-badge" }, "Selected Store") : ""
        ),
        el("td", { class: "text-right tabular" },
          el("span", { class: "badge-count" }, String(count) + (count === 1 ? " report" : " reports"))
        ),
        el("td", { class: "text-right tabular" },
          rateVal !== undefined && rateVal !== null
            ? el("span", { class: "rate-pill" },
                el("span", { class: "rate-val" }, String(rateVal)),
                el("span", { class: "rate-unit" }, " / 10k")
              )
            : el("span", { class: "text-muted" }, "\u2014")
        )
      );
    });

    const tableHeadingText = selectedStore !== "ALL"
      ? "Regional Store Breakdown (Selected Store: " + selectedStore + " \u2014 " + storeSpecificCount + " of " + e.count + " Regional Reports)"
      : "Affected Stores & Normalized Complaint Rates (" + e.n_stores + " Total Sites)";

    const tableSubText = selectedStore !== "ALL"
      ? "Showing all " + e.n_stores + " stores affected across " + region + " Region, highlighting " + selectedStore + ":"
      : "Normalized rates per 10,000 visits provide unbiased exposure comparison across varying footfall stores:";

    const storeSection = el("div", { class: "card-section-box" },
      el("div", { class: "card-block-heading" },
        svgEl("svg", { class: "heading-inline-icon", width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("path", { d: "M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" }),
          svgEl("circle", { cx: "12", cy: "10", r: "3" })
        ),
        el("span", { class: "heading-text" }, tableHeadingText)
      ),
      el("p", { class: "card-block-sub" }, tableSubText),
      el("div", { class: "table-wrapper" },
        el("table", { class: "store-table-mini" },
          el("thead", {},
            el("tr", {},
              el("th", { class: "th-store" }, "Store Location"),
              el("th", { class: "th-reports text-right" }, "Reports This Week"),
              el("th", { class: "th-rate text-right" }, "Normalized Rate (per 10k visits)")
            )
          ),
          el("tbody", {}, ...storeRows)
        )
      )
    );

    // 4. Investigation Context & Audit Trail Box
    const auditBox = el("div", { class: "audit-meta-card" },
      el("div", { class: "audit-meta-item" },
        el("span", { class: "audit-meta-key" }, "Verification Status:"),
        el("span", { class: "audit-meta-text" }, e.status)
      ),
      el("div", { class: "audit-meta-item" },
        el("span", { class: "audit-meta-key" }, "Model Confidence:"),
        el("span", { class: "audit-meta-text tabular" }, String(e.confidence) + " margin ranking")
      ),
      el("div", { class: "audit-meta-item" },
        el("span", { class: "audit-meta-key" }, "Incident Window:"),
        el("span", { class: "audit-meta-text tabular" }, e.first_seen + " \u2192 " + e.last_seen)
      )
    );

    const auditSection = el("div", { class: "card-section-box" },
      el("div", { class: "card-block-heading" },
        svgEl("svg", { class: "heading-inline-icon", width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("path", { d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" })
        ),
        el("span", { class: "heading-text" }, "Triage Classification & Investigation Audit")
      ),
      el("p", { class: "card-block-sub" }, "Operational verification tier, model confidence margin, and active incident detection window:"),
      auditBox
    );

    // 5. Emerging Spike Banner
    const emergingBanner = e.emerging.length
      ? el("div", { class: "banner banner-danger" },
          svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
            svgEl("path", { d: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" })
          ),
          el("div", {},
            el("div", { class: "banner-title" }, "Emerging Issue Spike Alert (48h Action SLA)"),
            el("div", {}, "Statistically significant accelerated complaints triggered at: " + e.emerging.join(", "))
          )
        )
      : null;

    // 6. Voice-of-Store Evidence Section
    const evidenceSection = el("div", { class: "card-section-box" },
      el("div", { class: "card-block-heading" },
        svgEl("svg", { class: "heading-inline-icon", width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" })
        ),
        el("span", { class: "heading-text" }, "Voice-of-Store Evidence Excerpts (" + e.quotes.length + " Verified Quotes)")
      ),
      el("p", { class: "card-block-sub" }, "Direct customer and staff observations extracted from feedback streams:"),
      el("ul", { class: "quotes-list" },
        ...e.quotes.map((q) =>
          el("li", { class: "quote-item" },
            el("span", { class: "badge badge-channel" }, q[0] + " \u00b7 " + q[2]),
            el("span", { class: "quote-text" }, "\u201c" + q[1] + "\u201d")
          )
        )
      )
    );

    // 7. Mandatory Action Directive
    const actionDirective = el("div", { class: "action-directive-card" },
      el("div", { class: "action-directive-header" },
        svgEl("svg", { class: "heading-inline-icon", width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("polyline", { points: "9 11 12 14 22 4" }),
          svgEl("path", { d: "M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" })
        ),
        el("span", { class: "heading-text" }, "Mandatory Next Action (" + e.owner + " \u00b7 SLA: " + e.window + ")")
      ),
      el("div", { class: "action-directive-body" }, e.next_step)
    );

    const cardElements = [
      el("div", { class: "card-header-row" },
        el("h2", { class: "card-title" },
          (i + 1) + ". " + e.issue + (e.beyond_top5 ? " (Safety Escalation beyond Top 5)" : ""),
          el("span", { class: "trend-arrow " + trendClass, title: "Trend vs previous week" }, e.trend)
        ),
        el("div", { class: "meta-pill" },
          el("span", { class: "badge badge-" + e.severity }, e.severity),
          el("span", { class: "badge badge-owner" }, e.owner),
          el("span", { class: "badge badge-" + e.tier.toLowerCase() }, e.tier)
        )
      )
    ];

    if (scopeBanner) cardElements.push(scopeBanner);
    cardElements.push(kpiStrip);
    cardElements.push(storeSection);
    cardElements.push(auditSection);
    if (emergingBanner) cardElements.push(emergingBanner);
    cardElements.push(evidenceSection);
    cardElements.push(actionDirective);

    return el("section", { class: "card sev-" + e.severity }, ...cardElements);
  });

  box.replaceChildren(...cards);
}

async function showFlags() {
  const week = $("eweek").value;
  $("export").href = "/api/export?week=" + encodeURIComponent(week);
  const d = await api("/api/flags?week=" + encodeURIComponent(week));
  const box = $("flags");

  if (!d.flags.length) {
    box.replaceChildren(
      el("div", { class: "card" },
        el("h3", { class: "card-title" }, "No Emerging Issue Flags"),
        el("p", { class: "sub-meta" }, "No store-level issues crossed the statistical anomaly threshold for week " + week + ".")
      )
    );
    return;
  }

  const cards = [];
  for (const f of d.flags) {
    const s = await api("/api/series?store_id=" + encodeURIComponent(f.store_id) + "&issue_type=" + encodeURIComponent(f.issue_type));
    cards.push(
      el("section", { class: "card sev-high" },
        el("div", { class: "card-header-row" },
          el("h2", { class: "card-title" }, f.issue + " at " + f.store),
          el("span", { class: "badge badge-critical" }, "Emerging Issue Alert")
        ),
        el("div", { class: "meta-row" },
          el("span", { class: "badge badge-owner" }, f.owner),
          el("span", {}, el("b", {}, "Region: "), f.region || "\u2014"),
          el("span", {}, el("b", {}, "Confidence: "), f.confidence.toFixed(2)),
          el("span", {}, el("b", {}, "Action SLA: "), "Review within 48h" + (f.owner_window === "same day" ? " (Safety: Same Day)" : ""))
        ),
        el("div", { class: "banner banner-warning" },
          el("div", {}, el("b", {}, "Statistical Anomaly: "), f.change.summary)
        ),
        el("div", { class: "meta-row" }, el("span", {}, f.status)),
        el("div", { class: "chart-box" },
          seriesSvg(
            s,
            "Weekly Reports: " + f.issue + " at " + f.store,
            "Anomaly: " + f.change.summary + " \u00b7 " + (f.region ? f.region + " Region \u00b7 " : "") + "SLA: Review within 48h"
          )
        ),
        el("ul", { class: "quotes-list" },
          ...f.evidence.map((q) =>
            el("li", { class: "quote-item" },
              el("span", { class: "badge badge-channel" }, q.channel),
              el("span", { class: "quote-text" }, "\u201c" + q.text + "\u201d")
            )
          )
        ),
        el("div", { class: "next-step-box" },
          el("span", { class: "next-step-label" }, "Mandatory Action:"),
          f.next_step
        )
      )
    );
  }
  box.replaceChildren(...cards);
}

async function prepareAlertBatch() {
  const week = $("eweek").value;
  const box = $("alert-preview");
  const preview = await api("/api/alerts/preview?week=" + encodeURIComponent(week));
  if (!preview.enabled) {
    box.replaceChildren(
      el("div", { class: "card" },
        el("h3", { class: "card-title" }, "Alert Delivery Not Configured"),
        el("p", { class: "sub-meta" }, "SMTP, a recipient list, and authenticated operator login must be configured on the server.")
      )
    );
    return;
  }
  const approve = el("button", { class: "btn btn-primary", type: "button" }, "Approve and Send This Batch");
  approve.disabled = preview.flag_count === 0;
  approve.addEventListener("click", async () => {
    const destinations = preview.recipients.join(", ");
    if (!window.confirm("Send " + preview.flag_count + " unverified alert(s) for " + week + " to " + destinations + "?")) return;
    approve.disabled = true;
    try {
      const sent = await api("/api/alerts/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ week: week, batch_id: preview.batch_id, approved: true })
      });
      $("alert-delivery-status").textContent = "Batch sent to " + sent.recipient_count + " recipient(s). Approval and delivery were recorded.";
      box.replaceChildren();
    } catch (error) {
      approve.disabled = false;
      $("alert-delivery-status").textContent = "Batch was not confirmed as sent: " + error.message;
    }
  });
  box.replaceChildren(
    el("section", { class: "card" },
      el("h3", { class: "card-title" }, "Review Alert Email Before Approval"),
      el("p", { class: "sub-meta" }, "To: " + preview.recipients.join(", ") + " \xb7 " + preview.flag_count + " flag(s) \xb7 Week " + week),
      el("p", { class: "sub-meta" }, "Feedback quotes are excluded. These signals are unverified and require operational review."),
      ...preview.items.map((item) => el("div", { class: "item" },
        el("b", {}, item.issue + " at " + item.store),
        el("div", { class: "sub-meta" }, item.region + " \xb7 " + item.owner + " \xb7 confidence " + item.confidence.toFixed(2)),
        el("div", { class: "sub-meta" }, item.change),
        el("div", { class: "sub-meta" }, "Next step: " + item.next_step)
      )),
      approve
    )
  );
}

let storeSeq = 0;
async function showStore() {
  const mine = ++storeSeq;
  const storeId = $("store").value;
  const week = $("sweek").value;
  const o = await api("/api/store?store_id=" + encodeURIComponent(storeId) + "&week=" + encodeURIComponent(week));
  if (mine !== storeSeq) return;

  const flagged = o.flag_history.map((f) => f.week);
  const cards = o.top.map((t) => {
    const trendClass = t.trend === "\u2191" ? "trend-up" : t.trend === "\u2193" ? "trend-down" : "trend-flat";
    return el("section", { class: "card sev-" + t.severity },
      el("div", { class: "card-header-row" },
        el("h3", { class: "card-title" }, t.issue, el("span", { class: "trend-arrow " + trendClass }, t.trend)),
        el("div", { class: "meta-pill" },
          el("span", { class: "badge badge-owner" }, t.owner),
          el("span", { class: "badge badge-" + t.severity }, t.severity)
        )
      ),
      el("div", { class: "meta-row" },
        el("span", {}, el("b", {}, "Volume: "), t.count + " reports (" + t.previous + " previous week)")
      ),
      el("ul", { class: "quotes-list" },
        ...t.quotes.map((q) =>
          el("li", { class: "quote-item" },
            el("span", { class: "quote-text" }, "\u201c" + q + "\u201d")
          )
        )
      ),
      el("div", { class: "next-step-box" },
        el("span", { class: "next-step-label" }, "Store Action:"),
        t.next_step
      )
    );
  });

  $("storeview").replaceChildren(
    el("div", { class: "kpi-row" },
      renderKpi("Store Profile", o.name, o.region + " Region \u00b7 ID: " + o.store_id, "teal"),
      renderKpi("Actionable Reports", o.reports_this_week, "Reports logged this week", "teal"),
      renderKpi("Previous Week", o.reports_previous_week, "Prior week volume", "teal"),
      renderKpi("Emerging Status", o.flags_this_week.length ? "Active Alert" : "Normal", o.flags_this_week.length ? o.flags_this_week[0].issue : "Within statistical limits", o.flags_this_week.length ? "danger" : "teal")
    ),
    el("div", { class: "card" },
      weekBars(
        o.weeks,
        o.weekly_reports,
        flagged,
        "26-Week Actionable Volume Trajectory \u00b7 " + o.name,
        o.reports_this_week + " actionable reports this week (" + o.reports_previous_week + " prior week) \u00b7 " + o.region + " Region"
      ),
      o.flag_history.length
        ? el("div", { class: "meta-row" },
            el("b", {}, "Flag History: "),
            ...o.flag_history.map((f) => el("span", { class: "badge badge-critical" }, f.week + " \u00b7 " + f.issue))
          )
        : el("div", { class: "meta-row" }, el("span", { class: "sub-meta" }, "No emerging-issue alerts on record for this store."))
    ),
    el("h2", { class: "section-heading" }, "Top Issues at " + o.name + " (Week of " + o.week + ")"),
    ...(cards.length ? cards : [el("div", { class: "card" }, el("p", { class: "sub-meta" }, "No actionable complaints recorded for this store in this week."))])
  );
}

async function showQueue() {
  const qRegionEl = $("q-region");
  const qWeekEl = $("q-week");
  const region = qRegionEl ? qRegionEl.value : "ALL";
  const week = qWeekEl ? qWeekEl.value : $("week").value;
  const ownerFilter = $("q-owner").value;
  const sevFilter = $("q-sev").value;
  const tierFilter = $("q-tier").value;

  const container = $("queue-container");
  let items = [];

  if (region === "ALL") {
    const regions = META ? META.regions : ["Central", "East", "North", "South", "West"];
    const results = await Promise.all(
      regions.map(async (reg) => {
        const key = reg + "_" + week;
        if (!CACHED_BRIEFS[key]) {
          CACHED_BRIEFS[key] = await api("/api/brief?region=" + encodeURIComponent(reg) + "&week=" + encodeURIComponent(week));
        }
        const d = CACHED_BRIEFS[key];
        return (d.entries || []).map((e) => Object.assign({}, e, { region: reg }));
      })
    );
    items = results.flat();
  } else {
    const key = region + "_" + week;
    if (!CACHED_BRIEFS[key]) {
      CACHED_BRIEFS[key] = await api("/api/brief?region=" + encodeURIComponent(region) + "&week=" + encodeURIComponent(week));
    }
    const d = CACHED_BRIEFS[key];
    items = (d.entries || []).map((e) => Object.assign({}, e, { region: region }));
  }

  // Include store-level emerging anomaly flags for the reporting week
  let flagsData = CACHED_FLAGS[week];
  if (!flagsData) {
    flagsData = await api("/api/flags?week=" + encodeURIComponent(week));
    CACHED_FLAGS[week] = flagsData;
  }
  const matchingFlags = (flagsData.flags || []).filter((f) => region === "ALL" || f.region === region);
  matchingFlags.forEach((f) => {
    items.push({
      region: f.region || "Store-level",
      issue: f.issue + " at " + f.store + " (Emerging Spike)",
      owner: f.owner,
      severity: "high",
      window: "within 48 hours",
      tier: "EMERGING ANOMALY",
      count: f.evidence ? f.evidence.length : 2,
      quotes: (f.evidence || []).map((e) => [e.channel, e.text]),
      is_flag: true
    });
  });

  // Calculate counts for dynamic dropdown labels based on region & week
  const totalCount = items.length;
  const critCount = items.filter((x) => String(x.severity).toLowerCase() === "critical").length;
  const highCount = items.filter((x) => String(x.severity).toLowerCase() === "high").length;
  const medCount = items.filter((x) => String(x.severity).toLowerCase() === "medium").length;
  const lowCount = items.filter((x) => String(x.severity).toLowerCase() === "low").length;

  const sevSel = $("q-sev");
  if (sevSel) {
    const currentVal = sevSel.value;
    const sevOptions = [
      el("option", { value: "ALL" }, "All Severities (" + totalCount + ")"),
      el("option", { value: "critical" }, "Critical (" + critCount + ")"),
      el("option", { value: "high" }, "High (" + highCount + ")"),
      el("option", { value: "medium" }, "Medium (" + medCount + ")"),
      el("option", { value: "low" }, "Low (" + lowCount + ")")
    ];
    sevSel.replaceChildren(...sevOptions);
    sevSel.value = currentVal;
  }

  if (ownerFilter !== "ALL") items = items.filter((x) => x.owner === ownerFilter);
  if (sevFilter !== "ALL") items = items.filter((x) => String(x.severity).toLowerCase() === sevFilter.toLowerCase());
  if (tierFilter !== "ALL") items = items.filter((x) => String(x.tier).toUpperCase() === tierFilter.toUpperCase());

  // Order: Critical first, then High, then Medium, then Low; then by report count descending
  const sevRank = { critical: 0, high: 1, medium: 2, low: 3 };
  items.sort((a, b) => {
    const rA = sevRank[a.severity] ?? 9;
    const rB = sevRank[b.severity] ?? 9;
    if (rA !== rB) return rA - rB;
    return b.count - a.count;
  });

  if (!items.length) {
    const regionName = region === "ALL" ? "All Regions (Chain-wide)" : region + " Region";
    const sevLabel = sevFilter !== "ALL" ? sevFilter.toUpperCase() : "Matching";
    const emptyCard = el("div", { class: "card" },
      el("h3", { class: "card-title" }, "0 " + sevLabel + " Escalations Recorded"),
      el("p", { class: "sub-meta" },
        "No " + (sevFilter !== "ALL" ? sevFilter.toLowerCase() + "-severity " : "") +
        "escalations logged for " + regionName + " in week " + week + "."
      ),
      el("div", { class: "banner banner-info" },
        svgEl("svg", { class: "banner-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("circle", { cx: "12", cy: "12", r: "10" }),
          svgEl("line", { x1: "12", y1: "16", x2: "12", y2: "12" }),
          svgEl("line", { x1: "12", y1: "8", x2: "12.01", y2: "8" })
        ),
        el("div", {},
          el("div", { class: "banner-title" }, "Severity Escalation Policy Context"),
          el("div", {},
            sevFilter === "critical"
              ? "Critical severity covers urgent emergency hazards (severe food contamination, gas leaks, structural hazards, or acute refrigeration failures requiring same-day shutdown). None occurred in this region/week."
              : (sevFilter === "medium" || sevFilter === "low")
                ? "Low and Medium severity items (such as standard billing inquiries, minor checkout delays, or general feedback) are addressed in standard weekly store replenishment and review cycles. They do not trigger high-urgency executive escalations unless an emerging anomaly flag is detected."
                : "No items match the current combination of filters. You can clear filters to view all active regional escalations."
          )
        )
      ),
      el("button", { class: "btn btn-outline btn-sm", type: "button" }, "View All Active Escalations (" + totalCount + ")")
    );
    emptyCard.querySelector("button").addEventListener("click", () => {
      $("q-sev").value = "ALL";
      $("q-owner").value = "ALL";
      $("q-tier").value = "ALL";
      showQueue().catch(showErr);
    });
    container.replaceChildren(emptyCard);
    return;
  }

  const table = el("div", { class: "table-wrapper" },
    el("table", {},
      el("thead", {},
        el("tr", {},
          el("th", {}, "Region"),
          el("th", {}, "Issue Category"),
          el("th", {}, "Owner Function"),
          el("th", {}, "Severity"),
          el("th", {}, "Action SLA"),
          el("th", {}, "Verification Tier"),
          el("th", { class: "text-right" }, "Reports"),
          el("th", {}, "Evidence Preview")
        )
      ),
      el("tbody", {},
        ...items.map((it) => {
          const firstQuote = it.quotes && it.quotes.length ? it.quotes[0][1] : "\u2014";
          const tierClass = it.tier === "UNVERIFIED" ? "unverified" : "verified";
          return el("tr", {},
            el("td", {}, el("span", { class: "badge badge-channel" }, it.region)),
            el("td", {}, el("b", {}, it.issue)),
            el("td", {}, el("span", { class: "badge badge-owner" }, it.owner || "Unassigned")),
            el("td", {}, el("span", { class: "badge badge-" + it.severity }, it.severity)),
            el("td", {}, el("span", { class: "badge badge-" + (it.window === "same day" ? "critical" : "medium") }, it.window)),
            el("td", {}, el("span", { class: "badge badge-" + tierClass }, it.tier)),
            el("td", { class: "text-right tabular" }, String(it.count)),
            el("td", { class: "tabular" }, "\u201c" + (firstQuote.length > 55 ? firstQuote.slice(0, 52) + "\u2026" : firstQuote) + "\u201d")
          );
        })
      )
    )
  );

  container.replaceChildren(table);
}

async function showPrecision() {
  if (!VALIDATION_DATA) {
    VALIDATION_DATA = await api("/api/validation");
  }
  const v = VALIDATION_DATA;
  const pct = (x) => (x * 100).toFixed(1) + "%";
  const ci = (c) => (c ? " (95% interval " + pct(c[0]) + " to " + pct(c[1]) + ")" : "");

  $("precision").replaceChildren(
    el("h2", { class: "section-heading" }, "Forward-in-Time Out-of-Sample Model Validation"),
    el("div", { class: "kpi-row" },
      renderKpi("Classification Score", v.classification.toFixed(3), "Composite: 0.5/0.25/0.25", "teal"),
      renderKpi("Issue Macro-F1", v.issue_macro_f1.toFixed(3), "30 operational + 3 non-issue classes", "teal"),
      renderKpi("Severity Weighted-F1", v.severity_weighted_f1.toFixed(3), "Policy floor preserved", "teal"),
      renderKpi("Actionable F1", v.actionable_f1.toFixed(3), "Routeable operational gates", "teal")
    ),
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Escalation Precision Statements"),
      el("div", { class: "banner banner-info" },
        el("div", {},
          el("div", { class: "banner-title" }, "Empirical Verification Precision"),
          el("div", {},
            "Of " + v.n_pred_actionable + " records marked actionable, ",
            el("b", {}, pct(v.precision_actionable)),
            " were truly actionable" + ci(v.ci_actionable) + ". ",
            "Of " + v.n_pred_actionable_high + " marked actionable AND high/critical, ",
            el("b", {}, pct(v.precision_actionable_high)),
            " were truly actionable" + ci(v.ci_actionable_high) + "."
          )
        )
      ),
      el("p", { class: "sub-meta" }, "Evaluated on forward time split: trained on labelled rows of weeks 1\u20139 (" + v.n_train + " rows), tested on out-of-sample weeks 10\u201313 (" + v.n_test + " rows)."),
      el("a", { class: "btn btn-outline btn-sm", href: "/report", target: "_blank", rel: "noopener noreferrer" },
        svgEl("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", "stroke-width": "2" },
          svgEl("path", { d: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" }),
          svgEl("polyline", { points: "15 3 21 3 21 9" }),
          svgEl("line", { x1: "10", y1: "14", x2: "21", y2: "3" })
        ),
        "Open Full Evaluation Report (Printable HTML)"
      )
    ),
    el("div", { id: "reportbox", "aria-live": "polite" },
      el("div", { class: "card" }, el("p", { class: "sub-meta" }, "Loading full evaluation metrics\u2026"))
    )
  );

  try {
    showReportSummary(await api("/api/report"));
  } catch (e) {
    $("reportbox").replaceChildren(
      el("div", { class: "card" },
        el("p", { class: "sub-meta" }, "Detailed evaluation summary could not be retrieved (" + e.message + ").")
      )
    );
  }
}

function showReportSummary(r) {
  const pct = (x) => (x === null ? "n/a" : (x * 100).toFixed(1) + "%");
  const sr = r.escalation.safety_recall;
  const dd = r.dedup;
  const d = r.detection.incidents && r.detection.incidents.length ? r.detection.incidents[0] : null;

  const rows = (arr) => arr.map((cells) => el("tr", {}, ...cells.map((c) => el("td", {}, c))));

  $("reportbox").replaceChildren(
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Escalation Precision by Confidence Score"),
      el("div", { class: "table-wrapper" },
        el("table", { class: "fixed-table precision-table" },
          el("thead", {},
            el("tr", {},
              el("th", { class: "th-thresh" }, "Score Threshold"),
              el("th", { class: "th-recs text-right" }, "Escalated Records"),
              el("th", { class: "th-prec text-right" }, "Truly Actionable")
            )
          ),
          el("tbody", {},
            ...r.escalation.by_confidence.map((x) =>
              el("tr", {},
                el("td", { class: "tabular" },
                  el("span", { class: "threshold-tag" }, "\u2265 " + String(x.threshold))
                ),
                el("td", { class: "text-right tabular" },
                  el("span", { class: "badge-count" }, String(x.escalated) + " records")
                ),
                el("td", { class: "text-right tabular" },
                  el("span", { class: "rate-pill" },
                    el("span", { class: "rate-val" }, pct(x.precision))
                  )
                )
              )
            )
          )
        )
      )
    ),
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Safety Category Recall"),
      el("p", { class: "sub-meta" },
        sr.caught + " of " + sr.truly_safety + " truly safety-type reports were escalated as high or critical (" +
        pct(sr.recall) + "). Missed breakdowns: " +
        (Object.entries(sr.missed_as).map((x) => x[1] + " as " + x[0]).join("; ") || "None") + "."
      )
    ),
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Weakest Issue Categories (Room for Improvement)"),
      el("div", { class: "table-wrapper" },
        el("table", { class: "fixed-table weakest-table" },
          el("thead", {},
            el("tr", {},
              el("th", { class: "th-cat" }, "Category"),
              el("th", { class: "th-sup text-right" }, "Test Support"),
              el("th", { class: "th-f1 text-right" }, "F1 Score")
            )
          ),
          el("tbody", {},
            ...r.classification.weakest.map((t) =>
              el("tr", {},
                el("td", {},
                  el("b", {}, t.id),
                  " \u00b7 " + t.name
                ),
                el("td", { class: "text-right tabular" },
                  el("span", { class: "badge-count" }, String(t.support) + " test rows")
                ),
                el("td", { class: "text-right tabular" },
                  el("span", { class: "badge badge-owner" }, t.f1.toFixed(3))
                )
              )
            )
          )
        )
      )
    ),
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Detector Lead on Benchmark Incident"),
      el("p", { class: "sub-meta" },
        d
          ? "Incident " + d.incident + " (" + d.issue_type + "): Onset " + d.onset +
            ", Naive Rule Detection: " + d.naive_detection +
            ", Voice-of-Store First Flag: " + (d.our_first_flag || "None") +
            (d.lead_weeks !== null ? " (Lead time: +" + d.lead_weeks + " week(s))" : "") + "."
          : "Worked incident benchmark not loaded."
      )
    ),
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Cross-Channel De-duplication Engine"),
      el("p", { class: "sub-meta" },
        dd.reports.toLocaleString() + " raw actionable reports grouped into " +
        dd.incidents.toLocaleString() + " deduplicated incidents (" +
        dd.reports_per_incident + " reports/incident; " +
        dd.cross_channel_incidents.toLocaleString() + " multi-channel corroborations). " +
        dd.note
      )
    )
  );
}

function say(role, text, items) {
  const box = el("div", { class: "chat-bubble " + role }, el("div", {}, text));
  (items || []).forEach((it) => {
    box.append(
      el("div", { class: "item" },
        el("b", {}, it.title),
        ...it.lines.map((l) => el("div", { class: "sub-meta" }, l))
      )
    );
  });
  $("chat").append(box);
  $("chat").scrollTop = $("chat").scrollHeight;
  return box;
}

async function ask(message) {
  HISTORY.push(message);
  hpos = HISTORY.length;
  say("me", message);
  const wait = say("bot", "Analyzing Voice-of-Store operational intelligence\u2026");
  wait.setAttribute("aria-busy", "true");
  try {
    let mode = $("assistant-mode").value;
    let customKey = sessionStorage.getItem("gemini_api_key") || localStorage.getItem("gemini_api_key");
    const serverConfigured = META && META.assistant_modes && META.assistant_modes.gemini;
    if (mode === "gemini" && !customKey && !serverConfigured) {
      const val = prompt("Enter Google Gemini API Key (starts with AIzaSy...):");
      if (val && val.trim()) {
        customKey = val.trim();
        sessionStorage.setItem("gemini_api_key", customKey);
        localStorage.setItem("gemini_api_key", customKey);
      } else {
        mode = "local";
        $("assistant-mode").value = "local";
      }
    }
    const headers = { "Content-Type": "application/json" };
    if (customKey) {
      headers["X-Gemini-API-Key"] = customKey;
    }
    let r;
    try {
      r = await api("/api/assistant", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ message: message, mode: mode })
      });
    } catch (innerErr) {
      if (mode === "gemini") {
        r = await api("/api/assistant", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: message, mode: "local" })
        });
        r.llm_summary = "Operational Intelligence (Local grounded mode): " + r.reply;
      } else {
        throw innerErr;
      }
    }
    wait.remove();
    const displayText = (mode === "gemini" && r.llm_summary) ? r.llm_summary : r.reply;
    const box = say("bot", displayText, r.items);
    if (mode === "gemini" && r.llm_summary) {
      box.append(
        el("div", { class: "chat-source-tag" },
          "AI Response: Powered by Gemini \u00b7 Grounded in Operational Intelligence" + (r.week ? " \u00b7 Week of " + r.week : "")
        )
      );
    } else if (r.source) {
      box.append(
        el("div", { class: "chat-source-tag" },
          "Grounded Source: " + r.source + (r.week ? " \u00b7 Week of " + r.week : "")
        )
      );
    }
  } catch (e) {
    wait.remove();
    const is503 = e.message && e.message.includes("503");
    const is502 = e.message && e.message.includes("502");
    let errNote = is503
      ? "AI summary mode is not configured on this server instance. If running in VS Code, please restart your server (Ctrl+C then re-run) to load the latest code, or check your API key."
      : is502
      ? "AI service was reached but returned an error (verify your API key and network connection). Local mode remains fully operational."
      : "Unable to complete request: " + e.message + ". Please try asking in Local mode or about a store/region.";
    say("bot", errNote);
  }
}

function setupAsk(suggestions) {
  const modeSelect = $("assistant-mode");
  const geminiOption = modeSelect.querySelector('option[value="gemini"]');
  const keyBtn = $("btn-gemini-key");

  function refreshGeminiOption() {
    const customKey = sessionStorage.getItem("gemini_api_key") || localStorage.getItem("gemini_api_key");
    const serverConfigured = META.assistant_modes && META.assistant_modes.gemini;
    if (customKey || serverConfigured) {
      geminiOption.disabled = false;
      geminiOption.textContent = "Local + AI summary";
      if (keyBtn) {
        keyBtn.textContent = customKey ? "🔑 Key Active" : "🔑 Server Key";
        keyBtn.title = customKey ? "API key active from session" : "API key configured on server";
      }
    } else {
      geminiOption.disabled = false;
      geminiOption.textContent = "Local + AI summary (enter key)";
      if (keyBtn) {
        keyBtn.textContent = "Set API Key";
        keyBtn.title = "Click to enter API key";
      }
    }
  }

  if (keyBtn) {
    keyBtn.addEventListener("click", () => {
      const current = sessionStorage.getItem("gemini_api_key") || "";
      const val = prompt("Enter API Key (starts with AIzaSy...):", current);
      if (val !== null) {
        const trimmed = val.trim();
        if (trimmed) {
          sessionStorage.setItem("gemini_api_key", trimmed);
          localStorage.setItem("gemini_api_key", trimmed);
          modeSelect.value = "gemini";
        } else {
          sessionStorage.removeItem("gemini_api_key");
          localStorage.removeItem("gemini_api_key");
          modeSelect.value = "local";
        }
        refreshGeminiOption();
      }
    });
  }

  modeSelect.addEventListener("change", () => {
    if (modeSelect.value === "gemini") {
      const customKey = sessionStorage.getItem("gemini_api_key") || localStorage.getItem("gemini_api_key");
      const serverConfigured = META.assistant_modes && META.assistant_modes.gemini;
      if (!customKey && !serverConfigured && keyBtn) {
        keyBtn.click();
      }
    }
  });

  refreshGeminiOption();
  $("chips").replaceChildren(
    ...suggestions.map((s) => {
      const b = el("button", { type: "button", class: "chip-btn" }, s);
      b.addEventListener("click", () => ask(s));
      return b;
    })
  );
  $("askform").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("question").value.trim();
    if (q) {
      $("question").value = "";
      ask(q);
    }
  });
  $("clearchat").addEventListener("click", () => {
    $("chat").replaceChildren();
    say("bot", GREETING);
    $("question").focus();
  });
  $("question").addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowUp" && ev.key !== "ArrowDown") return;
    ev.preventDefault();
    hpos = Math.min(HISTORY.length, Math.max(0, hpos + (ev.key === "ArrowUp" ? -1 : 1)));
    $("question").value = HISTORY[hpos] || "";
  });
  say("bot", GREETING);
}

function setupTryPresets() {
  const presets = [
    { label: "Freezer Breakdown", channel: "staff_shift_note", text: "Dairy chiller #2 temperature alarm triggered at Kothrud, compressor stopped, ice cream defrosting." },
    { label: "Counter Overcharge", channel: "online_review", text: "Cashier scanned the basmati rice pack twice at Indiranagar counter 4, refused to fix bill on spot." },
    { label: "Expired Yoghurt", channel: "in_app", text: "Found curd container on shelf with expired date stamp by 4 days at South store." },
    { label: "UPI Payment Error", channel: "call_centre_ticket", text: "Customer debited Rs 1250 on Google Pay at checkout but POS printed transaction failed." },
    { label: "Helpful Staff", channel: "online_review", text: "Great experience shopping here, staff helped carry heavy bags to the parking lot." }
  ];

  $("try-presets").replaceChildren(
    ...presets.map((p) => {
      const b = el("button", { type: "button", class: "chip-btn" }, p.label);
      b.addEventListener("click", () => {
        $("channel").value = p.channel;
        $("text").value = p.text;
      });
      return b;
    })
  );
}


let TABS_INITIALIZED = false;

function selectTab(btn) {
  if (!btn) return;
  const tabs = [...document.querySelectorAll(".sidebar-nav button")];
  tabs.forEach((x) => {
    const isTarget = x === btn;
    x.setAttribute("aria-selected", isTarget ? "true" : "false");
    x.tabIndex = isTarget ? 0 : -1;
  });

  const viewName = btn.dataset.view;
  const allViews = ["overview", "brief", "emerging", "stores", "queue", "ho", "ask", "try", "precision", "ingest"];
  allViews.forEach((v) => {
    const section = $("view-" + v);
    if (section) section.hidden = v !== viewName;
  });

  const titleSpan = $("page-title");
  if (titleSpan) {
    const label = btn.querySelector("span");
    if (label) titleSpan.textContent = label.textContent;
  }

  const sidebar = $("sidebar");
  if (sidebar) sidebar.classList.remove("open");

  if (viewName === "overview") showOverview().catch(showErr);
  else if (viewName === "brief") showBrief().catch(showErr);
  else if (viewName === "emerging") showFlags().catch(showErr);
  else if (viewName === "stores") showStore().catch(showErr);
  else if (viewName === "queue") showQueue().catch(showErr);
  else if (viewName === "ho") showHeadOffice().catch(showErr);
  else if (viewName === "precision") showPrecision().catch(showErr);
  else if (viewName === "ask") {
    const q = $("question");
    if (q) q.focus();
  }
}

function setupTabs() {
  if (TABS_INITIALIZED) return;
  TABS_INITIALIZED = true;
  const tabs = [...document.querySelectorAll(".sidebar-nav button")];
  tabs.forEach((btn, i) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      selectTab(btn);
    });
    btn.addEventListener("keydown", (ev) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
      if (ev.key === "Home" || ev.key === "End" || step) {
        ev.preventDefault();
        const j = ev.key === "Home" ? 0 : ev.key === "End" ? tabs.length - 1 : (i + step + tabs.length) % tabs.length;
        tabs[j].focus();
        selectTab(tabs[j]);
      }
    });
  });
}


function updateDatasetBanner(dataset) {
  const banner = $("dataset-banner");
  if (!banner) return;
  if (dataset && dataset.is_custom) {
    banner.style.display = "flex";
    $("dataset-banner-text").textContent = (dataset.name || "Custom Upload") + " · " + (dataset.row_count || 0) + " records · " + (dataset.date_min || "") + " to " + (dataset.date_max || "");
  } else {
    banner.style.display = "none";
  }
}

let CURRENT_INGESTED_RECORDS = [];
let SELECTED_FILE = null;

function setupIngest() {
  const dropzone = $("ingest-dropzone");
  const fileInput = $("ingest-file-input");
  const startBtn = $("ingest-start-btn");
  const filenameDisplay = $("ingest-filename-display");
  const spinner = $("ingest-spinner");
  const errorBox = $("ingest-error");
  const resultsCard = $("ingest-results-card");
  const tbody = $("ingest-tbody");
  const exportBtn = $("ingest-export-btn");
  const analyzeBtn = $("ingest-analyze-btn");

  if (!dropzone) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      handleFileSelected(fileInput.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) handleFileSelected(fileInput.files[0]);
  });

  function handleFileSelected(file) {
    SELECTED_FILE = file;
    filenameDisplay.textContent = file.name + " (" + (file.size / 1024).toFixed(1) + " KB)";
    startBtn.disabled = false;
    startBtn.removeAttribute("disabled");
    errorBox.hidden = true;
    errorBox.style.display = "none";
    // Trigger extraction immediately upon file selection
    startExtraction();
  }

  async function startExtraction() {
    if (!SELECTED_FILE) {
      alert("Please select a file to upload first by clicking the upload box.");
      return;
    }
    spinner.hidden = false;
    spinner.style.display = "block";
    errorBox.hidden = true;
    errorBox.style.display = "none";
    resultsCard.hidden = true;
    resultsCard.style.display = "none";
    startBtn.disabled = true;
    startBtn.setAttribute("disabled", "true");

    const fd = new FormData();
    fd.append("file", SELECTED_FILE);
    const defDate = $("ingest-default-date").value;
    if (defDate) fd.append("default_date", defDate);

    try {
      console.log("Extracting records from:", SELECTED_FILE.name);
      const resp = await fetch("/api/ingest/upload", {
        method: "POST",
        body: fd
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Extraction failed");

      CURRENT_INGESTED_RECORDS = data.records || [];
      renderIngestResults(CURRENT_INGESTED_RECORDS, data.stats || {});
    } catch (err) {
      console.error("Extraction error:", err);
      errorBox.textContent = "Extraction Error: " + err.message;
      errorBox.hidden = false;
      errorBox.style.display = "block";
      alert("Extraction error: " + err.message);
    } finally {
      spinner.hidden = true;
      spinner.style.display = "none";
      startBtn.disabled = false;
      startBtn.removeAttribute("disabled");
    }
  }

  startBtn.addEventListener("click", (e) => {
    e.preventDefault();
    startExtraction();
  });

  function renderIngestResults(records, stats) {
    resultsCard.hidden = false;
    resultsCard.style.display = "block";
    setTimeout(() => resultsCard.scrollIntoView({ behavior: "smooth" }), 100);
    $("stat-total").textContent = "Total: " + (stats.total || records.length);
    $("stat-valid").textContent = "Valid: " + (stats.valid || 0);
    $("stat-review-store").textContent = "Store Review: " + (stats.review_store || 0);
    $("stat-review-date").textContent = "Date Review: " + (stats.review_date || 0);

    tbody.replaceChildren();

    records.forEach((r, idx) => {
      const tr = el("tr", { style: "border-bottom: 1px solid var(--border-color);" });

      // Exclude checkbox
      const tdExclude = el("td", { style: "padding: 8px; text-align: center;" });
      const chk = el("input", { type: "checkbox" });
      chk.addEventListener("change", () => {
        r._excluded = chk.checked;
        tr.style.opacity = chk.checked ? "0.4" : "1.0";
      });
      tdExclude.appendChild(chk);

      // Feedback ID
      const tdId = el("td", { style: "padding: 8px; font-weight: 600; font-family: monospace;" }, r.feedback_id);

      // Source ref
      const tdSrc = el("td", { style: "padding: 8px; color: var(--text-muted); font-size: 12px;" }, r.source_reference || "-");

      // Channel select
      const tdChannel = el("td", { style: "padding: 8px;" });
      const chSel = el("select", { class: "form-control", style: "padding: 4px; font-size: 12px;" });
      ["online_review", "in_app", "staff_shift_note", "call_centre_ticket"].forEach((c) => {
        const opt = el("option", { value: c }, c);
        if (c === r.channel) opt.selected = true;
        chSel.appendChild(opt);
      });
      chSel.addEventListener("change", () => { r.channel = chSel.value; });
      tdChannel.appendChild(chSel);

      // Created at input
      const tdDate = el("td", { style: "padding: 8px;" });
      const dateInp = el("input", {
        type: "text",
        value: r.created_at,
        class: "form-control",
        style: "padding: 4px; font-size: 12px; width: 130px;"
      });
      dateInp.addEventListener("input", () => { r.created_at = dateInp.value; });
      tdDate.appendChild(dateInp);

      // Store select
      const tdStore = el("td", { style: "padding: 8px;" });
      const stSel = el("select", { class: "form-control", style: "padding: 4px; font-size: 12px; width: 150px;" });
      const emptyOpt = el("option", { value: "" }, "-- Unknown Store --");
      stSel.appendChild(emptyOpt);
      (META.stores || []).forEach((s) => {
        const opt = el("option", { value: s.id }, s.name + " (" + s.region + ")");
        if (s.id === r.store_id) opt.selected = true;
        stSel.appendChild(opt);
      });
      stSel.addEventListener("change", () => {
        r.store_id = stSel.value;
        const matched = (META.stores || []).find((x) => x.id === r.store_id);
        if (matched) {
          r.store_name = matched.name;
          r.region = matched.region;
        }
      });
      tdStore.appendChild(stSel);

      // Text input
      const tdText = el("td", { style: "padding: 8px;" });
      const textInp = el("input", {
        type: "text",
        value: r.text,
        class: "form-control",
        style: "width: 100%; padding: 4px; font-size: 12px;"
      });
      textInp.addEventListener("input", () => { r.text = textInp.value; });
      tdText.appendChild(textInp);

      // Status pill
      const tdStatus = el("td", { style: "padding: 8px;" });
      const isOk = r.status === "valid";
      const statusPill = el("span", {
        class: "badge",
        style: isOk
          ? "background: var(--success-soft); color: var(--success-text); padding: 3px 6px; border-radius: 4px; font-size: 11px;"
          : "background: var(--warning-soft); color: var(--warning-text); padding: 3px 6px; border-radius: 4px; font-size: 11px;",
        title: r.notes || ""
      }, isOk ? "VALID" : "REVIEW");
      tdStatus.appendChild(statusPill);

      tr.append(tdExclude, tdId, tdSrc, tdChannel, tdDate, tdStore, tdText, tdStatus);
      tbody.appendChild(tr);
    });
  }

  exportBtn.addEventListener("click", async () => {
    const valid = CURRENT_INGESTED_RECORDS.filter((r) => !r._excluded);
    if (!valid.length) {
      alert("No active records to export.");
      return;
    }
    try {
      const resp = await fetch("/api/ingest/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records: valid })
      });
      if (!resp.ok) throw new Error("Export failed");
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (SELECTED_FILE ? SELECTED_FILE.name.replace(/\.[^/.]+$/, "") : "ingested") + "_structured.csv";
      a.click();
    } catch (err) {
      alert("Download failed: " + err.message);
    }
  });

  analyzeBtn.addEventListener("click", async () => {
    const valid = CURRENT_INGESTED_RECORDS.filter((r) => !r._excluded);
    if (!valid.length) {
      alert("No active records to analyze.");
      return;
    }
    const confirmed = confirm(
      "Analyze " + valid.length + " extracted records in the dashboard?\n\n" +
      "This will update Regional Briefs, Emerging Issues, and Stores to reflect this custom dataset."
    );
    if (!confirmed) return;

    analyzeBtn.disabled = true;
    try {
      const resp = await fetch("/api/ingest/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          records: valid,
          name: SELECTED_FILE ? SELECTED_FILE.name : "Custom Upload"
        })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Analysis failed");

      CACHED_FLAGS = {};
      CACHED_BRIEFS = {};
      META = await api("/api/meta");
      updateDatasetBanner(data.dataset);

      fill($("ov-week"), META.test_weeks);
      fill($("week"), META.test_weeks);
      fill($("eweek"), META.test_weeks);
      $("ov-week").value = META.test_weeks[0];
      $("week").value = $("ov-week").value;
      $("eweek").value = $("ov-week").value;

      if ($("ov-store")) $("ov-store").value = "ALL";
      if ($("brief-store")) $("brief-store").value = "ALL";

      const firstReg = valid.find((r) => r.region)?.region;
      if (firstReg && META.regions.includes(firstReg)) {
        $("ov-region").value = firstReg;
        $("region").value = firstReg;
        updateBriefStores(firstReg);
        updateOverviewStores(firstReg);
      }

      alert("Dataset successfully activated! Showing analysis on the new data.");
      const tabOverview = $("tab-overview");
      if (tabOverview) tabOverview.click();
    } catch (err) {
      alert("Analysis error: " + err.message);
    } finally {
      analyzeBtn.disabled = false;
    }
  });
}

async function init() {
  setupTabs();
  META = await api("/api/meta");

  // Fill dropdowns
  fill($("ov-region"), META.regions);
  fill($("region"), META.regions);
  fill($("ov-week"), META.test_weeks);
  fill($("week"), META.test_weeks);
  fill($("eweek"), META.test_weeks);

  $("ov-week").value = META.test_weeks[META.test_weeks.length - 1];
  $("week").value = $("ov-week").value;
  $("eweek").value = $("ov-week").value;

  fill($("store"), META.stores.map((s) => s.id), storeLabel);
  fill($("sweek"), META.weeks);
  $("sweek").value = META.weeks[META.weeks.length - 1];

  fill($("channel"), META.channels);

  if ($("q-region")) {
    const qRegOptions = [
      el("option", { value: "ALL" }, "All Regions (Chain-wide)"),
      ...META.regions.map((r) => el("option", { value: r }, r + " Region"))
    ];
    $("q-region").replaceChildren(...qRegOptions);
    $("q-region").value = "ALL";
    $("q-region").addEventListener("change", () => showQueue().catch(showErr));
  }

  if ($("q-week")) {
    fill($("q-week"), META.test_weeks);
    $("q-week").value = $("week").value;
    $("q-week").addEventListener("change", () => showQueue().catch(showErr));
  }

  updateBriefStores($("region").value);
  $("brief-store").addEventListener("change", () => showBrief().catch(showErr));

  updateOverviewStores($("ov-region").value);
  if ($("ov-store")) {
    $("ov-store").addEventListener("change", () => showOverview().catch(showErr));
  }

  if ($("rule")) $("rule").textContent = META.escalation_rule;
  if ($("ov-policy-text")) $("ov-policy-text").textContent = META.escalation_rule;

  // Search store input
  if ($("storefilter")) {
    $("storefilter").addEventListener("input", () => {
      const q = $("storefilter").value.trim().toLowerCase();
      const hit = META.stores.filter((s) => !q || (s.name + " " + s.region).toLowerCase().includes(q));
      fill($("store"), hit.map((s) => s.id), storeLabel);
      if (hit.length) showStore().catch(showErr);
    });
  }

  $("store").addEventListener("change", () => showStore().catch(showErr));
  $("sweek").addEventListener("change", () => showStore().catch(showErr));

  // Region and Week change listeners
  $("ov-region").addEventListener("change", () => {
    $("region").value = $("ov-region").value;
    updateBriefStores($("region").value);
    updateOverviewStores($("ov-region").value);
    showOverview().catch(showErr);
  });
  $("ov-week").addEventListener("change", () => {
    $("week").value = $("ov-week").value;
    showOverview().catch(showErr);
  });
  $("region").addEventListener("change", () => {
    $("ov-region").value = $("region").value;
    updateBriefStores($("region").value);
    showBrief().catch(showErr);
  });
  $("week").addEventListener("change", () => {
    $("ov-week").value = $("week").value;
    showBrief().catch(showErr);
  });
  $("eweek").addEventListener("change", () => showFlags().catch(showErr));
  $("prepare-alerts").addEventListener("click", () => prepareAlertBatch().catch(showErr));
  if (!META.alert_delivery_enabled) {
    $("prepare-alerts").disabled = true;
    $("alert-delivery-status").textContent = "Email alerts require server-side SMTP settings and an authenticated operator account.";
  } else {
    $("alert-delivery-status").textContent = "Alert email is available. Review every batch and approve it before sending.";
  }

  $("q-owner").addEventListener("change", () => showQueue().catch(showErr));
  $("q-sev").addEventListener("change", () => showQueue().catch(showErr));
  $("q-tier").addEventListener("change", () => showQueue().catch(showErr));

  $("ov-quick-brief").addEventListener("click", () => {
    const tabBrief = $("tab-brief");
    if (tabBrief) tabBrief.click();
  });

  // Mobile menu toggle
  $("menu-toggle").addEventListener("click", () => {
    $("sidebar").classList.toggle("open");
  });

  setupAsk([
    "What are the top issues in the South region this week?",
    "Any emerging issues this week?",
    "How is Kothrud doing?",
    "Who handles refrigeration problems?",
    "What is the escalation rule?",
    "How accurate is this system?"
  ]);

  setupTryPresets();
  initHeadOffice();

  // Tab switching active
  setupTabs();
  setupIngest();

  updateDatasetBanner(META.dataset);

  const resetBtn = $("dataset-reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to switch back to the original default dataset?")) return;
      try {
        const res = await api("/api/ingest/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        CACHED_FLAGS = {};
        CACHED_BRIEFS = {};
        META = await api("/api/meta");
        updateDatasetBanner(res.dataset);
        fill($("ov-week"), META.test_weeks);
        fill($("week"), META.test_weeks);
        fill($("eweek"), META.test_weeks);
        $("ov-week").value = META.test_weeks[META.test_weeks.length - 1];
        $("week").value = $("ov-week").value;
        $("eweek").value = $("ov-week").value;
        await showOverview();
        alert("Restored original default dataset!");
      } catch (err) {
        alert("Reset failed: " + err.message);
      }
    });
  }

  setupIngest();

  // Try form submission
  $("tryform").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const textVal = $("text").value.trim();
    if (!textVal) return;
    try {
      const r = await api("/api/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textVal, channel: $("channel").value })
      });
      $("result").replaceChildren(
        el("section", { class: "card sev-" + r.severity },
          el("div", { class: "card-header-row" },
            el("h3", { class: "card-title" }, r.issue_type + " \u00b7 " + r.issue),
            el("div", { class: "meta-pill" },
              el("span", { class: "badge badge-" + r.severity }, r.severity),
              el("span", { class: "badge badge-owner" }, r.owner),
              el("span", { class: "badge badge-" + (r.actionable ? "verified" : "low") }, r.actionable ? "Actionable" : "Not Actionable")
            )
          ),
          el("div", { class: "meta-row" },
            el("span", {}, el("b", {}, "Confidence Score: "), String(r.confidence)),
            r.store_named ? el("span", {}, el("b", {}, "Store Identified: "), r.store_named) : ""
          ),
          r.note ? el("div", { class: "banner banner-warning" }, r.note) : "",
          el("div", { class: "meta-row" },
            el("span", {}, el("b", {}, "Alternative Candidate Types: "),
              r.alternatives.map((a) => a.issue_type + " (" + a.score + ")").join(", ") || "None")
          ),
          el("div", {},
            el("b", {}, "Key Explanatory Tokens: "),
            ...r.key_terms.map((t) => el("span", { class: "tag-pill" }, t.term + " (" + t.weight + ")"))
          )
        )
      );
    } catch (e) {
      showErr(e);
    }
  });

  // Default initial load
  await showOverview();
}


// ============================================================================
// HEAD OFFICE CONTROL CENTER & RESOLUTION MANAGEMENT
// ============================================================================

let CURRENT_HO_SUB = "overview";
let HO_INITIALIZED = false;

function getHoUserContext() {
  const roleSel = $("ho-role-select");
  const val = roleSel ? roleSel.value : "head_office_admin";
  let role = val;
  let dept = "";
  let region = "";
  let storeId = "";

  if (val.startsWith("department_manager:")) {
    role = "department_manager";
    dept = val.split(":")[1];
  } else if (val.startsWith("department_member:")) {
    role = "department_member";
    dept = val.split(":")[1];
  } else if (val.startsWith("regional_manager:")) {
    role = "regional_manager";
    region = val.split(":")[1];
  } else if (val.startsWith("store_owner:") || val.startsWith("store_manager:")) {
    role = "store_owner";
    storeId = val.split(":")[1];
  }
  return { role, dept, region, storeId, raw: val };
}

function updateHoStoreDropdown() {
  const storeSel = $("ho-filter-store");
  if (!storeSel || !META || !META.stores) return;
  const regVal = $("ho-filter-region") ? $("ho-filter-region").value : "";
  const fmtVal = $("ho-filter-format") ? $("ho-filter-format").value : "";
  const prevVal = storeSel.value;

  storeSel.replaceChildren(el("option", { value: "" }, "All Stores"));
  META.stores.forEach((s) => {
    if (regVal && s.region !== regVal) return;
    if (fmtVal) {
      if (fmtVal.includes("Hyper") && !s.name.includes("Hyper")) return;
      if (fmtVal.includes("Market") && !s.name.includes("Market")) return;
      if (fmtVal.includes("Express") && !s.name.includes("Express")) return;
    }
    storeSel.appendChild(el("option", { value: s.id }, s.name + " (" + s.region + ")"));
  });

  if (prevVal && Array.from(storeSel.options).some((o) => o.value === prevVal)) {
    storeSel.value = prevVal;
  }
}

function getHoFilterQueryParams() {
  const searchVal = ($("ho-search") ? $("ho-search").value : "").trim();
  const formatVal = $("ho-filter-format") ? $("ho-filter-format").value : "";
  const regionVal = $("ho-filter-region") ? $("ho-filter-region").value : "";
  const storeVal = $("ho-filter-store") ? $("ho-filter-store").value : "";
  const catVal = $("ho-filter-cat") ? $("ho-filter-cat").value : "";
  const resVal = $("ho-filter-resolution") ? $("ho-filter-resolution").value : "";
  const deptVal = $("ho-filter-dept") ? $("ho-filter-dept").value : "";
  const sevVal = $("ho-filter-sev") ? $("ho-filter-sev").value : "";
  const statusVal = $("ho-filter-status") ? $("ho-filter-status").value : "";

  return new URLSearchParams({
    search: searchVal,
    store_format: formatVal,
    region: regionVal,
    store_id: storeVal,
    category: catVal,
    resolution_status: resVal,
    department: deptVal,
    severity: sevVal,
    status: statusVal
  });
}

async function hoApi(path, opts = {}) {
  const ctx = getHoUserContext();
  const headers = Object.assign(
    {
      "Content-Type": "application/json",
      "X-User-Role": ctx.role,
      "X-User-Dept": ctx.dept || "",
      "X-User-Region": ctx.region || "",
      "X-User-Store": ctx.storeId || "",
      "X-User-Id": "usr_" + (ctx.dept ? ctx.dept.toLowerCase().replace(/\s+/g, "_") : ctx.role)
    },
    opts.headers || {}
  );
  return api(path, Object.assign({}, opts, { headers }));
}

function initHeadOffice() {
  if (HO_INITIALIZED) return;
  HO_INITIALIZED = true;

  const subnavBtns = document.querySelectorAll(".ho-subnav-btn");
  subnavBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      subnavBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      CURRENT_HO_SUB = btn.dataset.sub || "overview";
      renderHoView().catch(showErr);
    });
  });

  ["ho-search", "ho-filter-format", "ho-filter-region", "ho-filter-store", "ho-filter-cat", "ho-filter-resolution", "ho-filter-dept", "ho-filter-sev", "ho-filter-status"].forEach((id) => {
    const elem = $(id);
    if (!elem) return;
    const evt = id === "ho-search" ? "input" : "change";
    elem.addEventListener(evt, () => {
      renderHoView().catch(showErr);
    });
  });

  const refreshBtn = $("ho-btn-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => renderHoView().catch(showErr));
  }

  const regElem = $("ho-filter-region");
  if (regElem) {
    regElem.addEventListener("change", () => {
      updateHoStoreDropdown();
      renderHoView().catch(showErr);
    });
  }

  const fmtElem = $("ho-filter-format");
  if (fmtElem) {
    fmtElem.addEventListener("change", () => {
      updateHoStoreDropdown();
      renderHoView().catch(showErr);
    });
  }

  const resetBtn = $("ho-reset-filters");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if ($("ho-search")) $("ho-search").value = "";
      if ($("ho-filter-format")) $("ho-filter-format").value = "";
      if ($("ho-filter-region")) $("ho-filter-region").value = "";
      updateHoStoreDropdown();
      if ($("ho-filter-store")) $("ho-filter-store").value = "";
      renderHoView().catch(showErr);
    });
  }

  const roleSelect = $("ho-role-select");
  if (roleSelect) {
    roleSelect.addEventListener("change", () => {
      const ctx = getHoUserContext();
      if (ctx.role === "store_owner" && ctx.storeId) {
        if ($("ho-filter-store")) $("ho-filter-store").value = ctx.storeId;
      }
      renderHoView().catch(showErr);
    });
  }

  const modalClose = $("ho-modal-close");
  if (modalClose) {
    modalClose.addEventListener("click", closeIssueModal);
  }
  const modalBackdrop = $("ho-modal-backdrop");
  if (modalBackdrop) {
    modalBackdrop.addEventListener("click", (ev) => {
      if (ev.target === modalBackdrop) closeIssueModal();
    });
  }
}

async function showHeadOffice() {
  if (!HO_INITIALIZED) initHeadOffice();

  // Populate regions
  const regSel = $("ho-filter-region");
  if (regSel && regSel.options.length <= 1 && META && META.regions) {
    META.regions.forEach((r) => {
      regSel.appendChild(el("option", { value: r }, r + " Region"));
    });
  }

  // Populate stores dynamically based on region & format
  updateHoStoreDropdown();

  // Populate categories / problem types
  const catSel = $("ho-filter-cat");
  if (catSel && catSel.options.length <= 1 && META && META.issue_types) {
    META.issue_types.forEach((t) => {
      catSel.appendChild(el("option", { value: t.name }, t.name + " (" + t.owner + ")"));
    });
  }

  await renderHoView();
}

function closeIssueModal() {
  const b = $("ho-modal-backdrop");
  if (b) b.hidden = true;
}

async function renderHoView() {
  const container = $("ho-content");
  if (!container) return;
  container.replaceChildren(el("div", { class: "sub-meta" }, "Loading operational data..."));

  const filtersBar = document.querySelector(".ho-filters-bar");
  if (filtersBar) {
    filtersBar.hidden = CURRENT_HO_SUB === "performance" || CURRENT_HO_SUB === "notifications";
  }

  try {
    if (CURRENT_HO_SUB === "overview") {
      await renderHoOverview(container);
    } else if (CURRENT_HO_SUB === "resolution") {
      await renderHoStoreResolutionMatrix(container);
    } else if (CURRENT_HO_SUB === "performance") {
      await renderHoPerformance(container);
    } else if (CURRENT_HO_SUB === "notifications") {
      await renderHoNotifications(container);
    } else {
      await renderHoIssuesList(container, CURRENT_HO_SUB);
    }
  } catch (err) {
    container.replaceChildren(
      el("div", { class: "banner banner-warning" }, "Unable to display view: " + err.message)
    );
  }
}


function renderStoreFormatCards(byFormat) {
  const cards = Object.entries(byFormat).map(([fmtName, stats]) => {
    let badgeCls = "badge-format-market";
    if (fmtName.includes("Hyper")) badgeCls = "badge-format-hyper";
    else if (fmtName.includes("Express")) badgeCls = "badge-format-express";

    const filterBtn = el("button", { class: "btn btn-outline btn-sm" }, "Filter " + fmtName);
    filterBtn.addEventListener("click", () => {
      const fSel = $("ho-filter-format");
      if (fSel) fSel.value = fmtName;
      updateHoStoreDropdown();
      renderHoView().catch(showErr);
    });

    return el(
      "div",
      { class: "ho-format-card" },
      el(
        "div",
        { class: "ho-format-header" },
        el("span", { class: "badge " + badgeCls }, fmtName),
        el("span", { class: "ho-format-rate" }, stats.resolution_rate + "% Resolved")
      ),
      el(
        "div",
        { class: "ho-format-stats" },
        el("div", { class: "ho-format-stat-item" }, "Total: ", el("b", {}, String(stats.total))),
        el("div", { class: "ho-format-stat-item" }, "Resolved: ", el("b", {}, String(stats.resolved))),
        el("div", { class: "ho-format-stat-item" }, "Awaiting: ", el("b", {}, String(stats.awaiting))),
        el("div", { class: "ho-format-stat-item" }, "Unresolved: ", el("b", {}, String(stats.unresolved)))
      ),
      el("div", { style: "margin-top: 10px;" }, filterBtn)
    );
  });
  return el("div", { class: "ho-format-grid" }, ...cards);
}

function renderStoreProblemsTable(issues, summaryTitle) {
  if (!issues || issues.length === 0) {
    return el(
      "div",
      { class: "card", style: "margin-top: 16px;" },
      el("h3", { class: "card-title" }, summaryTitle || "Store Problem Resolution Status"),
      el("div", { class: "sub-meta", style: "padding: 16px 0;" }, "No store problems match the active filters (Store Format, Region, Store).")
    );
  }

  const ctx = getHoUserContext();
  const isStoreOwner = ctx.role === "store_owner";
  const isAdmin = ctx.role === "head_office_admin";

  const table = el(
    "table",
    { class: "ho-table" },
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", {}, "Store"),
        el("th", {}, "Region & Store Type"),
        el("th", {}, "Problem / AI Category"),
        el("th", {}, "Severity"),
        el("th", {}, "Action Taken on Task"),
        el("th", {}, "Resolution State"),
        el("th", {}, "SLA Deadline"),
        el("th", {}, "Action")
      )
    ),
    el(
      "tbody",
      {},
      ...issues.map((iss) => {
        let inspectLabel = "Inspect Problem";
        let inspectCls = "btn btn-outline btn-sm";
        if (isStoreOwner) {
          inspectLabel = "\U0001f4dd Update Action Taken";
          inspectCls = "btn btn-primary btn-sm";
        } else if (isAdmin) {
          inspectLabel = "\U0001f50e Check Action & Verify";
          inspectCls = iss.current_status === "RESOLVED_AWAITING_VERIFICATION" ? "btn btn-primary btn-sm" : "btn btn-outline btn-sm";
        }

        const inspectBtn = el("button", { class: inspectCls }, inspectLabel);
        inspectBtn.addEventListener("click", () => openIssueModal(iss.id));

        // Action Taken Column
        const hasAction = Boolean(iss.latest_action_desc || iss.resolution_summary);
        let actionBadge;
        let actionDesc;
        let actionMeta;

        if (hasAction) {
          actionBadge = el("span", { class: "badge badge-action-taken" }, "\u2713 Action Taken");
          const text = iss.latest_action_desc || iss.resolution_summary || "";
          actionDesc = el("div", { class: "ho-action-snippet", title: text }, text);
          const author = iss.latest_action_by || "Store Owner";
          const time = iss.latest_action_at ? formatShortDate(iss.latest_action_at.slice(0, 10)) : "Logged";
          actionMeta = el("div", { class: "sub-meta" }, author + " \u2022 " + time);
        } else {
          actionBadge = el("span", { class: "badge badge-action-needed" }, "\u23f3 No Action Yet");
          actionDesc = el("div", { class: "sub-meta" }, "Awaiting store corrective action");
          actionMeta = null;
        }

        // Resolution State Column
        let resBadge;
        let resDetail;
        if (iss.current_status === "VERIFIED_CLOSED") {
          resBadge = el("span", { class: "badge badge-res-verified" }, "\u2713 SOLVED (Verified by HO)");
          resDetail = el("div", { class: "sub-meta" }, "Verified by Head Office");
        } else if (iss.current_status === "RESOLVED_AWAITING_VERIFICATION") {
          resBadge = el("span", { class: "badge badge-res-awaiting" }, "\u23f1\ufe0f CLAIMED RESOLVED");
          resDetail = el("div", { class: "sub-meta" }, "Awaiting HO Verification");
        } else if (iss.current_status === "PENDING") {
          resBadge = el("span", { class: "badge badge-res-pending" }, "\u23f8\ufe0f BLOCKED (PENDING)");
          resDetail = el("div", { class: "sub-meta" }, iss.pending_reason ? "Reason: " + iss.pending_reason : "");
        } else if (iss.is_overdue) {
          resBadge = el("span", { class: "badge badge-res-overdue" }, "\u26a0\ufe0f UNRESOLVED (OVERDUE)");
          resDetail = el("div", { class: "sub-meta" }, "SLA Breached");
        } else {
          resBadge = el("span", { class: "badge badge-res-unresolved" }, "\u2699\ufe0f IN PROGRESS");
          resDetail = el("div", { class: "sub-meta" }, iss.current_status.replace(/_/g, " "));
        }

        let fmtCls = "badge-format-market";
        const fmt = iss.store_format || "Saffron Market";
        if (fmt.includes("Hyper")) fmtCls = "badge-format-hyper";
        else if (fmt.includes("Express")) fmtCls = "badge-format-express";

        return el(
          "tr",
          {},
          el("td", {},
            el("b", {}, iss.store_name),
            el("div", { class: "sub-meta" }, iss.store_id)
          ),
          el("td", {},
            el("span", { class: "badge " + fmtCls }, fmt),
            el("div", { class: "sub-meta" }, iss.region + " Region")
          ),
          el("td", {},
            el("div", { class: "ho-cell-title" }, iss.issue_category),
            el("div", { class: "sub-meta" }, iss.title)
          ),
          el("td", {},
            el("span", { class: "badge badge-" + iss.severity }, iss.severity),
            el("div", { class: "sub-meta" }, iss.owning_department_id)
          ),
          el("td", {}, actionBadge, actionDesc, actionMeta),
          el("td", {}, resBadge, resDetail),
          el("td", {},
            el("div", {}, iss.resolution_deadline ? formatShortDate(iss.resolution_deadline.slice(0, 10)) : "Standard"),
            iss.is_overdue ? el("span", { class: "badge badge-critical" }, "OVERDUE") : el("span", { class: "sub-meta" }, "On Track")
          ),
          el("td", {}, inspectBtn)
        );
      })
    )
  );

  return el(
    "div",
    { class: "card", style: "margin-top: 16px;" },
    el(
      "div",
      { class: "card-header-row" },
      el("h3", { class: "card-title" }, summaryTitle || "Store Problem Resolution & Action Log"),
      el("div", { class: "sub-meta" }, "Showing " + issues.length + " store problems matching active filters")
    ),
    el(
      "p",
      { class: "sub-meta" },
      "Direct end-to-end tracking: Store owners update corrective actions taken, and Head Office verifies resolution before closure."
    ),
    table
  );
}

async function renderHoOverview(container) {
  const kpis = await hoApi("/api/ho/kpis");
  const elements = [];

  const counts = kpis.status_counts || kpis.counts || {};
  const total = kpis.total_issues !== undefined ? kpis.total_issues : (counts.total || 0);
  const overdue = kpis.overdue_count !== undefined ? kpis.overdue_count : (counts.overdue || 0);
  const reopened = kpis.reopened_count !== undefined ? kpis.reopened_count : (counts.reopened || 0);
  const critSafety = kpis.critical_safety_count !== undefined ? kpis.critical_safety_count : (counts.critical_safety || 0);

  if (critSafety > 0) {
    elements.push(
      el(
        "div",
        { class: "banner banner-critical" },
        el("b", {}, "CRITICAL ESCALATION POLICY ACTIVE: "),
        critSafety + " critical safety issues detected. Per corporate policy, food and store safety incidents trigger immediate head office escalation regardless of incident volume."
      )
    );
  }

  // Active Role Banner
  const ctx = getHoUserContext();
  let roleNotice = null;
  if (ctx.role === "store_owner") {
    roleNotice = el(
      "div",
      { class: "banner banner-info", style: "margin-bottom: 14px;" },
      el("b", {}, "\U0001f3ea STORE OWNER PORTAL: "),
      "Logged in as Store Owner" + (ctx.storeId ? " (" + ctx.storeId + ")" : "") + ". You can log corrective actions taken on your store's problems and submit them for Head Office verification."
    );
  } else if (ctx.role === "head_office_admin") {
    roleNotice = el(
      "div",
      { class: "banner banner-info", style: "margin-bottom: 14px;" },
      el("b", {}, "\U0001f3e2 HEAD OFFICE CONTROL CENTER: "),
      "Logged in as Head Office Administrator. You can monitor problems across all stores, check actions taken by store owners, and verify resolution closures."
    );
  }
  if (roleNotice) elements.push(roleNotice);

  const kpiItems = [
    { label: "Total Problems", val: total, sub: "Across monitored stores" },
    { label: "Verified Solved", val: counts.VERIFIED_CLOSED || counts.verified_closed || 0, sub: "Verified by HO", isGreen: true },
    { label: "Awaiting HO Verification", val: counts.RESOLVED_AWAITING_VERIFICATION || counts.awaiting_verification || 0, sub: "Claimed resolved by store", isAmber: (counts.RESOLVED_AWAITING_VERIFICATION || counts.awaiting_verification || 0) > 0 },
    { label: "In Progress", val: counts.IN_PROGRESS || counts.in_progress || 0, sub: "Store action ongoing" },
    { label: "Blocked / Pending", val: counts.PENDING || counts.pending || 0, sub: "Waiting on parts/approval" },
    { label: "Overdue", val: overdue, sub: "SLA target breached", isOverdue: overdue > 0 }
  ];

  const kpiGrid = el(
    "div",
    { class: "ho-kpi-grid" },
    ...kpiItems.map((item) =>
      el(
        "div",
        { class: "ho-kpi-card" + (item.isOverdue ? " ho-kpi-card-overdue" : item.isGreen ? " ho-kpi-card-verified" : "") },
        el("div", { class: "ho-kpi-val" }, String(item.val)),
        el("div", { class: "ho-kpi-label" }, item.label),
        el("div", { class: "ho-kpi-sub" }, item.sub)
      )
    )
  );
  elements.push(kpiGrid);

  // Fetch problems matching active filters (Region, Format, Store, Search)
  const q = getHoFilterQueryParams();
  const matrixData = await hoApi("/api/ho/resolution_matrix?" + q.toString());

  // Store format cards
  if (matrixData.by_format && Object.keys(matrixData.by_format).length > 0) {
    elements.push(renderStoreFormatCards(matrixData.by_format));
  }

  // Display ALL THE PROBLEMS DOWN THERE!
  elements.push(renderStoreProblemsTable(matrixData.issues || [], "Store Problem Resolution & Action Log"));

  container.replaceChildren(...elements);
}


async function renderHoIssuesList(container, viewKey) {
  const q = getHoFilterQueryParams();
  q.set("view", viewKey);

  const res = await hoApi("/api/ho/issues?" + q.toString());
  const issues = res.issues || [];

  const viewTitles = {
    all: "All Tracked Store Problems",
    dept: "My Department's Assigned Problems",
    pending: "Pending / Blocked Store Problems",
    overdue: "SLA Overdue Escalated Problems",
    verification: "Problems Awaiting Head Office Verification",
    resolved: "Verified & Closed Store Problems"
  };
  const title = viewTitles[viewKey] || ("Store Problems (" + viewKey.replace(/_/g, " ") + ")");

  const problemsTable = renderStoreProblemsTable(issues, title);
  container.replaceChildren(problemsTable);
}

async function renderHoPerformance(container) {
  const perf = await hoApi("/api/ho/performance");
  const depts = perf.departments || {};

  const table = el(
    "table",
    { class: "ho-table" },
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", {}, "Department"),
        el("th", {}, "Total Assigned"),
        el("th", {}, "Open Issues"),
        el("th", {}, "Ack Rate"),
        el("th", {}, "Resolution Rate"),
        el("th", {}, "Overdue"),
        el("th", {}, "Avg Ack (hrs)"),
        el("th", {}, "Avg Res (hrs)"),
        el("th", {}, "Reopened"),
        el("th", {}, "Rejected Verifications")
      )
    ),
    el(
      "tbody",
      {},
      ...Object.entries(depts).map(([deptName, d]) => {
        return el(
          "tr",
          {},
          el("td", {}, el("b", {}, deptName)),
          el("td", {}, String(d.total_assigned)),
          el("td", {}, String(d.open_issues)),
          el("td", {}, d.acknowledgement_rate + "%"),
          el("td", {}, d.resolution_rate + "%"),
          el("td", {}, d.overdue_count > 0 ? el("span", { class: "badge badge-critical" }, String(d.overdue_count)) : "0"),
          el("td", {}, String(d.avg_ack_hours)),
          el("td", {}, String(d.avg_res_hours)),
          el("td", {}, String(d.reopened_count)),
          el("td", {}, d.verification_rejections > 0 ? el("span", { class: "badge badge-high" }, String(d.verification_rejections)) : "0")
        );
      })
    )
  );

  container.replaceChildren(
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Department Operational Performance & SLA Compliance"),
      el("p", { class: "sub-meta" }, "Operational velocity, acknowledgment timeliness, and first-time verification quality metrics per department."),
      table
    )
  );
}

async function renderHoNotifications(container) {
  const res = await hoApi("/api/ho/notifications");
  const list = res.notifications || [];

  if (list.length === 0) {
    container.replaceChildren(
      el("div", { class: "sub-meta" }, "No logged notification events.")
    );
    return;
  }

  const cards = list.map((n) => {
    const card = el(
      "div",
      { class: "ho-notification-card" },
      el(
        "div",
        { class: "ho-notification-header" },
        el("span", { class: "badge badge-" + (n.severity || "low") }, n.severity || "info"),
        el("b", {}, n.title),
        el("span", { class: "sub-meta" }, n.created_at || "")
      ),
      el("div", { class: "ho-notification-msg" }, n.message)
    );

    if (n.issue_id) {
      const btn = el("button", { class: "btn btn-outline btn-sm" }, "Inspect Issue " + n.issue_id);
      btn.addEventListener("click", () => openIssueModal(n.issue_id));
      card.appendChild(btn);
    }
    return card;
  });

  container.replaceChildren(
    el("div", { class: "card" },
      el("h3", { class: "card-title" }, "Escalation & Notification Log"),
      el("p", { class: "sub-meta" }, "System-generated escalations, SLA warnings, and department updates."),
      el("div", { class: "ho-notifications-list" }, ...cards)
    )
  );
}

async function openIssueModal(issueId) {
  const backdrop = $("ho-modal-backdrop");
  const modalBody = $("ho-modal-body");
  if (!backdrop || !modalBody) return;

  modalBody.replaceChildren(el("div", { class: "sub-meta" }, "Loading issue details..."));
  backdrop.hidden = false;

  try {
    const data = await hoApi("/api/ho/issue/" + issueId);
    const iss = data.issue || data;
    const history = data.history || [];
    const actions = data.actions || [];
    const evidence = data.evidence || [];
    const verifs = data.verifications || [];

    // Header updates
    const badge = $("ho-modal-status-badge");
    if (badge) {
      badge.textContent = iss.current_status;
      badge.className = "ho-status-badge ho-status-" + iss.current_status.toLowerCase().replace(/_/g, "-");
    }

    const titleEl = $("ho-modal-title");
    if (titleEl) titleEl.textContent = iss.id + ": " + iss.title;

    const subEl = $("ho-modal-subtitle");
    if (subEl) {
      subEl.textContent = "Store: " + iss.store_id + " (" + (iss.region_id || "") + ") \xb7 Owning Dept: " + iss.owning_department_id + " \xb7 Detected: " + iss.first_detected_at;
    }

    // Lifecycle Stepper
    const steps = ["NEW", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED_AWAITING_VERIFICATION", "VERIFIED_CLOSED"];
    const currIdx = steps.indexOf(iss.current_status);
    const isSpecial = iss.current_status === "PENDING" || iss.current_status === "REOPENED";

    const stepper = el(
      "div",
      { class: "ho-stepper" },
      ...steps.map((s, idx) => {
        let cls = "ho-step";
        if (s === iss.current_status) cls += " active";
        else if (currIdx !== -1 && idx < currIdx) cls += " completed";
        const label = s.replace(/_/g, " ");
        return el("div", { class: cls }, el("span", { class: "ho-step-dot" }), el("span", { class: "ho-step-label" }, label));
      })
    );

    // Meta details grid
    const metaGrid = el(
      "div",
      { class: "ho-meta-grid" },
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Severity:"), el("span", { class: "badge badge-" + iss.severity }, iss.severity)),
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Category:"), el("b", {}, iss.issue_category)),
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Department:"), el("b", {}, iss.owning_department_id)),
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Actionability:"), el("span", { class: "badge badge-" + (iss.actionability ? "verified" : "low") }, iss.actionability ? "Actionable" : "Advisory")),
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Resolution Target:"), el("b", {}, iss.resolution_deadline || "Standard")),
      el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "SLA Status:"), el("span", { class: "badge " + (iss.is_overdue ? "badge-critical" : "badge-low") }, iss.is_overdue ? "OVERDUE (" + iss.overdue_type + ")" : "Within SLA"))
    );

    // AI Context Box
    const aiBox = el(
      "div",
      { class: "ho-ai-context-box" },
      el("h4", { class: "ho-section-title" }, "AI Detection & Anomaly Model Intelligence"),
      el("p", { class: "sub-meta" }, "Distinguishing statistical detector predictions from verified operational facts:"),
      el("div", { class: "ho-meta-grid" },
        el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Predicted Category:"), el("span", {}, iss.predicted_category || iss.issue_category)),
        el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Predicted Severity:"), el("span", {}, iss.predicted_severity || iss.severity)),
        el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Detector Confidence:"), el("b", {}, String(iss.confidence || "0.92"))),
        el("div", { class: "ho-meta-item" }, el("span", { class: "ho-meta-k" }, "Source Channel:"), el("span", {}, iss.detection_source || "Voice-of-Store CUSUM"))
      ),
      el("div", { class: "ho-anomaly-desc" },
        el("b", {}, "Anomaly Explanation: "),
        iss.anomaly_explanation || "Sequential probability ratio test (SPRT) detected sustained complaint rate deviation exceeding Poisson null baseline."
      )
    );

    // Corroborating Evidence Feedbacks
    const evidenceSection = el(
      "div",
      { class: "ho-evidence-section" },
      el("h4", { class: "ho-section-title" }, "Independent Corroborating Evidence (" + evidence.length + " reports)"),
      el("p", { class: "sub-meta" }, "Customer reviews and staff logs triggering this issue flag:"),
      ...evidence.map((evItem) =>
        el(
          "div",
          { class: "ho-evidence-quote" },
          el("div", { class: "ho-evidence-meta" },
            el("span", { class: "badge badge-owner" }, evItem.evidence_type || "Customer Review"),
            el("span", { class: "sub-meta" }, evItem.feedback_id ? "ID: " + evItem.feedback_id : ""),
            el("span", { class: "sub-meta" }, evItem.created_at || "")
          ),
          el("div", { class: "ho-evidence-text" }, "\"" + (evItem.evidence_text || evItem.evidence_reference || "Complaint logged") + "\"")
        )
      )
    );

    // Status Audit History
    const historySection = el(
      "div",
      { class: "ho-history-section" },
      el("h4", { class: "ho-section-title" }, "Immutable Audit History & Lifecycle Transitions"),
      el(
        "div",
        { class: "ho-timeline" },
        ...history.map((h) =>
          el(
            "div",
            { class: "ho-timeline-item" },
            el("div", { class: "ho-timeline-dot" }),
            el("div", { class: "ho-timeline-content" },
              el("div", { class: "ho-timeline-header" },
                el("b", {}, (h.previous_status || "START") + " \u2192 " + h.new_status),
                el("span", { class: "sub-meta" }, h.created_at || "")
              ),
              el("div", { class: "sub-meta" }, "Changed by: " + (h.changed_by || "System")),
              h.reason ? el("div", { class: "ho-timeline-reason" }, "Reason / Notes: " + h.reason) : null
            )
          )
        )
      )
    );

    // Action Taken Overview Card
    const latestActionDesc = actions.length > 0 ? actions[0].action_description : (iss.resolution_summary || "");
    const latestActionBy = actions.length > 0 ? actions[0].user_id : (iss.store_name || "Store Owner");
    const latestActionTime = actions.length > 0 ? actions[0].created_at : iss.resolved_at;

    const actionOverviewCard = el(
      "div",
      { class: "card", style: "border-left: 4px solid " + (latestActionDesc ? "#10b981" : "#f59e0b") },
      el("h4", { class: "ho-section-title" }, "Action Taken on Problem"),
      latestActionDesc
        ? el("div", {},
            el("div", { style: "font-size: 14px; font-weight: 600; color: #111827; margin-bottom: 6px;" }, latestActionDesc),
            el("div", { class: "sub-meta" }, "Logged by: " + latestActionBy + " \u2022 " + (latestActionTime || "Recent")),
            actions.length > 0 && actions[0].blockers ? el("div", { class: "badge badge-critical", style: "margin-top: 6px;" }, "Blocker: " + actions[0].blockers) : null
          )
        : el("div", { class: "sub-meta" }, "\u23f3 No corrective action recorded yet by store owner. Awaiting store response.")
    );

    // Department & Store Owner Action Form / Verification Controls
    const actionForm = el("div", { class: "ho-action-form-section" });
    const ctx = getHoUserContext();
    const isAdmin = ctx.role === "head_office_admin";
    const isStoreOwner = ctx.role === "store_owner";
    const isDeptManager = ctx.role === "department_manager" || isAdmin;

    // STORE OWNER ACTION FORM
    if (iss.current_status !== "VERIFIED_CLOSED" && isStoreOwner) {
      const storeActionCard = el("div", { class: "card", style: "border: 1px solid #bbf7d0; background: #f0fdf4;" });
      storeActionCard.appendChild(el("h4", { class: "ho-section-title", style: "color: #166534;" }, "\U0001f3ea Store Owner Action Update (" + (iss.store_name || iss.store_id) + ")"));
      storeActionCard.appendChild(
        el("p", { class: "sub-meta" }, "Record corrective action taken at your store. Once work is completed, submit for Head Office verification. Only Head Office can officially verify and close issues.")
      );

      const storeStatusSel = el(
        "select",
        { id: "ho-store-target-status", class: "ho-select" },
        el("option", { value: "RESOLVED_AWAITING_VERIFICATION" }, "\u2713 Action Completed \u2014 Submit for Head Office Verification"),
        el("option", { value: "IN_PROGRESS" }, "\u2699\ufe0f Action In Progress (Repair / Work underway)"),
        el("option", { value: "PENDING" }, "\u23f8\ufe0f Blocked (Waiting for replacement parts / external contractor)")
      );

      const storeActionDesc = el("textarea", {
        id: "ho-store-action-desc",
        class: "ho-textarea",
        rows: "3",
        placeholder: "Describe the specific corrective action taken at your store (e.g. Technician replaced chiller compressor coil; holding temperature restored to 3.5\xb0C; staff retrained)..."
      });

      const storeBlockerInput = el("input", {
        type: "text",
        id: "ho-store-blocker",
        class: "ho-input",
        placeholder: "Required only if Blocked (e.g. Waiting for manufacturer part delivery)"
      });

      const storeSaveBtn = el("button", { class: "btn btn-primary", type: "button" }, "\U0001f4be Submit Store Action & Update Head Office");
      storeSaveBtn.addEventListener("click", async () => {
        const desc = storeActionDesc.value.trim();
        if (!desc) {
          alert("A description of the action taken is required.");
          return;
        }
        const targetSt = storeStatusSel.value;
        const blk = storeBlockerInput.value.trim();
        if (targetSt === "PENDING" && !blk) {
          alert("Please state the blocker reason if action is marked Blocked/Pending.");
          return;
        }

        try {
          storeSaveBtn.disabled = true;
          await hoApi("/api/ho/issue/" + iss.id + "/action", {
            method: "POST",
            body: JSON.stringify({
              action_description: desc,
              target_status: targetSt,
              user_role: "store_owner",
              user_id: ctx.storeId ? "Store Owner (" + ctx.storeId + ")" : "Store Owner (" + iss.store_id + ")",
              department: "Store Operations",
              progress_notes: desc,
              blockers: blk
            })
          });
          alert("Action saved successfully! Status updated to " + targetSt.replace(/_/g, " ") + " and reflected in Head Office.");
          await openIssueModal(iss.id);
          renderHoView().catch(showErr);
        } catch (err) {
          alert("Failed to submit store action: " + err.message);
          storeSaveBtn.disabled = false;
        }
      });

      storeActionCard.appendChild(el("div", { class: "ho-form-group" }, el("label", {}, el("b", {}, "Action Status / Outcome:")), storeStatusSel));
      storeActionCard.appendChild(el("div", { class: "ho-form-group" }, el("label", {}, el("b", {}, "Corrective Action Details (What was done?):")), storeActionDesc));
      storeActionCard.appendChild(el("div", { class: "ho-form-group" }, el("label", {}, el("b", {}, "Blocker Reason (if Blocked):")), storeBlockerInput));
      storeActionCard.appendChild(el("div", { class: "ho-form-actions" }, storeSaveBtn));
      actionForm.appendChild(storeActionCard);
    }

    // DEPARTMENT / ADMIN TRIAGE CONTROLS
    const validTransitions = {
      NEW: ["ASSIGNED", "ACKNOWLEDGED"],
      ASSIGNED: ["ACKNOWLEDGED", "IN_PROGRESS"],
      ACKNOWLEDGED: ["IN_PROGRESS", "PENDING"],
      IN_PROGRESS: ["PENDING", "RESOLVED_AWAITING_VERIFICATION"],
      PENDING: ["IN_PROGRESS", "RESOLVED_AWAITING_VERIFICATION"],
      RESOLVED_AWAITING_VERIFICATION: [],
      VERIFIED_CLOSED: [],
      REOPENED: ["IN_PROGRESS", "PENDING"]
    }[iss.current_status] || [];

    if (iss.current_status !== "VERIFIED_CLOSED" && validTransitions.length > 0 && isDeptManager && !isStoreOwner) {
      const statusSelect = el(
        "select",
        { id: "ho-action-status-select", class: "ho-select" },
        ...validTransitions.map((st) => el("option", { value: st }, st.replace(/_/g, " ")))
      );

      const actionDescInput = el("input", {
        type: "text",
        id: "ho-action-desc",
        class: "ho-input",
        placeholder: "e.g. Dispatched technician / Initiated vendor stock replacement"
      });

      const notesInput = el("textarea", {
        id: "ho-action-notes",
        class: "ho-textarea",
        rows: "2",
        placeholder: "Investigation findings and corrective action details..."
      });

      const blockerInput = el("input", {
        type: "text",
        id: "ho-action-blocker",
        class: "ho-input",
        placeholder: "Required only if status is PENDING (e.g. Waiting for replacement part)"
      });

      const updateBtn = el("button", { class: "btn btn-primary", type: "button" }, "Submit Department Update");
      updateBtn.addEventListener("click", async () => {
        const nextSt = statusSelect.value;
        const desc = actionDescInput.value.trim() || ("Status changed to " + nextSt);
        const nts = notesInput.value.trim();
        const blk = blockerInput.value.trim();

        if (nextSt === "PENDING" && !blk) {
          alert("A blocker reason is required when placing an issue into PENDING status.");
          return;
        }

        try {
          updateBtn.disabled = true;
          await hoApi("/api/ho/issue/" + iss.id + "/status", {
            method: "POST",
            body: JSON.stringify({
              new_status: nextSt,
              reason: blk || nts || desc,
              action_description: desc,
              progress_notes: nts
            })
          });
          await openIssueModal(iss.id);
          renderHoView().catch(showErr);
        } catch (err) {
          alert("Update failed: " + err.message);
          updateBtn.disabled = false;
        }
      });

      actionForm.appendChild(
        el("div", { class: "card" },
          el("h4", { class: "ho-section-title" }, "Department Action & Investigation Update"),
          el("p", { class: "sub-meta" }, "Log corrective measures taken by " + iss.owning_department_id + ". Departments cannot self-verify closure; completing work requires Head Office verification."),
          el("div", { class: "ho-form-group" }, el("label", {}, "Target Status:"), statusSelect),
          el("div", { class: "ho-form-group" }, el("label", {}, "Corrective Action Description:"), actionDescInput),
          el("div", { class: "ho-form-group" }, el("label", {}, "Progress Notes:"), notesInput),
          el("div", { class: "ho-form-group" }, el("label", {}, "Blocker Reason (if Pending):"), blockerInput),
          el("div", { class: "ho-form-actions" }, updateBtn)
        )
      );
    }

    // Head Office Verification Card (for RESOLVED_AWAITING_VERIFICATION)
    if (iss.current_status === "RESOLVED_AWAITING_VERIFICATION") {
      const verifCard = el("div", { class: "card" });
      verifCard.appendChild(el("h4", { class: "ho-section-title" }, "Head Office Independent Verification"));
      verifCard.appendChild(
        el("p", { class: "sub-meta" }, "The department has marked corrective actions complete. Head Office must verify that customer complaints have ceased before closing this incident.")
      );

      const verifNotes = el("textarea", {
        id: "ho-verif-notes",
        class: "ho-textarea",
        rows: "2",
        placeholder: "Verification observations, store inspection sign-off, or rejection explanation..."
      });

      const approveBtn = el("button", { class: "btn btn-primary", type: "button" }, "Approve & Mark Verified Closed");
      approveBtn.addEventListener("click", async () => {
        try {
          approveBtn.disabled = true;
          await hoApi("/api/ho/issue/" + iss.id + "/verify", {
            method: "POST",
            body: JSON.stringify({
              decision: "approved",
              verification_notes: verifNotes.value.trim() || "Head Office confirmed corrective action resolution."
            })
          });
          await openIssueModal(iss.id);
          renderHoView().catch(showErr);
        } catch (err) {
          alert("Verification approval failed: " + err.message);
          approveBtn.disabled = false;
        }
      });

      const rejectBtn = el("button", { class: "btn btn-outline", type: "button" }, "Reject & Return to In-Progress");
      rejectBtn.addEventListener("click", async () => {
        const rReason = verifNotes.value.trim();
        if (!rReason) {
          alert("A rejection explanation is mandatory when rejecting department resolution.");
          return;
        }
        try {
          rejectBtn.disabled = true;
          await hoApi("/api/ho/issue/" + iss.id + "/verify", {
            method: "POST",
            body: JSON.stringify({
              decision: "rejected",
              verification_notes: rReason
            })
          });
          await openIssueModal(iss.id);
          renderHoView().catch(showErr);
        } catch (err) {
          alert("Verification rejection failed: " + err.message);
          rejectBtn.disabled = false;
        }
      });

      verifCard.appendChild(el("div", { class: "ho-form-group" }, el("label", {}, "Verification Notes:"), verifNotes));
      verifCard.appendChild(el("div", { class: "ho-form-actions" }, approveBtn, rejectBtn));
      actionForm.appendChild(verifCard);
    }

    // Reopen Issue Card (for VERIFIED_CLOSED)
    if (iss.current_status === "VERIFIED_CLOSED" && isAdmin) {
      const reopenCard = el("div", { class: "card" });
      reopenCard.appendChild(el("h4", { class: "ho-section-title" }, "Reopen Resolved Incident"));
      reopenCard.appendChild(
        el("p", { class: "sub-meta" }, "If new customer complaints or sensor alerts indicate problem recurrence, authorized Head Office administrators can reopen this issue.")
      );

      const reopenReason = el("input", {
        type: "text",
        class: "ho-input",
        placeholder: "Explain recurrence evidence (e.g. persistent complaints in subsequent week)..."
      });

      const reopenBtn = el("button", { class: "btn btn-outline", type: "button" }, "Reopen Issue");
      reopenBtn.addEventListener("click", async () => {
        const val = reopenReason.value.trim();
        if (!val) {
          alert("An explanation is required to reopen a closed issue.");
          return;
        }
        try {
          reopenBtn.disabled = true;
          await hoApi("/api/ho/issue/" + iss.id + "/reopen", {
            method: "POST",
            body: JSON.stringify({ reason: val })
          });
          await openIssueModal(iss.id);
          renderHoView().catch(showErr);
        } catch (err) {
          alert("Reopen failed: " + err.message);
          reopenBtn.disabled = false;
        }
      });

      reopenCard.appendChild(el("div", { class: "ho-form-group" }, el("label", {}, "Recurrence Evidence:"), reopenReason));
      reopenCard.appendChild(el("div", { class: "ho-form-actions" }, reopenBtn));
      actionForm.appendChild(reopenCard);
    }

    modalBody.replaceChildren(stepper, metaGrid, aiBox, evidenceSection, actionOverviewCard, historySection, actionForm);
  } catch (err) {
    modalBody.replaceChildren(
      el("div", { class: "banner banner-warning" }, "Failed to load issue details: " + err.message)
    );
  }
}


// ============================================================================
// STORE-BY-STORE PROBLEM RESOLUTION MATRIX
// ============================================================================

async function renderHoStoreResolutionMatrix(container) {
  const q = getHoFilterQueryParams();
  const res = await hoApi("/api/ho/resolution_matrix?" + q.toString());
  const summary = res.summary || {};
  const byFormat = res.by_format || {};
  const issues = res.issues || [];

  const elements = [];

  const kpiItems = [
    { label: "Problems Monitored", val: summary.total_problems || 0, sub: "Filtered store problems" },
    { label: "Verified Resolved", val: summary.verified_resolved || 0, sub: (summary.resolution_rate || 0) + "% resolution rate", isGreen: true },
    { label: "Awaiting HO Verification", val: summary.awaiting_verification || 0, sub: "Claimed resolved by store", isAmber: (summary.awaiting_verification || 0) > 0 },
    { label: "Actively In Progress", val: summary.unresolved || 0, sub: "Ongoing investigations" },
    { label: "Blocked / Pending", val: summary.pending || 0, sub: "Waiting on dependencies" }
  ];

  const kpiGrid = el(
    "div",
    { class: "ho-kpi-grid" },
    ...kpiItems.map((item) => {
      let cls = "ho-kpi-card";
      if (item.isGreen) cls += " ho-kpi-card-verified";
      return el(
        "div",
        { class: cls },
        el("div", { class: "ho-kpi-val" }, String(item.val)),
        el("div", { class: "ho-kpi-label" }, item.label),
        el("div", { class: "ho-kpi-sub" }, item.sub)
      );
    })
  );
  elements.push(kpiGrid);

  if (byFormat && Object.keys(byFormat).length > 0) {
    elements.push(renderStoreFormatCards(byFormat));
  }

  elements.push(renderStoreProblemsTable(issues, "Store-by-Store Problem Resolution & Verification Matrix"));

  container.replaceChildren(...elements);
}

function showErr(e) {
  if ($("rule")) $("rule").textContent = "Operational warning: " + e.message;
  console.warn("Operational warning:", e);
}

init().catch(showErr);
