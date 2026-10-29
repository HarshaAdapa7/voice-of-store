# Two-minute demo script

Setup (before the jury): `pip install -r FULL_CODE/requirements.txt`, put the pack files in `data/`, run
`python FULL_CODE/serve.py` (about 20 seconds to load) and open http://127.0.0.1:8000.

1. **The problem (15 s).** "Head office gets 40,000 messages in four channels and three languages. The real problems, a broken
   freezer or a wrong allergen label, are buried. We turn that into a weekly action list per region, routed to an owner."
2. **Weekly brief (30 s).** Pick South, the last week. Point at the top item: owner, severity, evidence tier
   (UNVERIFIED / CORROBORATED / POSSIBLE SYSTEMIC), the incident count after merging cross-channel duplicates, the trend arrow,
   real quotes. "Safety, allergen, hygiene and misconduct are never below high; a single report is labelled unverified."
   Click "Open printable page": one page per region.
3. **Emerging issues (30 s).** Open the tab. "A store reporting an issue clearly above its own normal rate, small but rising,
   at most three flags a week. Red bar is the flagged week; the cited evidence is underneath." Mention the worked example: caught one
   week before the naive detector.
4. **Try a comment (20 s).** Paste `frzr 3 not cooling since morning at Kothrud, ice cream melting` as a shift note. Show owner,
   severity, actionable, the store found in the text and the key terms. Paste `<script>alert(1)</script>` to show it stays inert.
5. **Precision and honesty (25 s).** Open Precision: "Of records we mark actionable, 95% truly are (interval 93.1-96.7%), measured
   forward in time. Limits: one visible incident to tune on, small labelled sample, synthetic data, no reporter ids."
6. **Responsibility (10 s).** "Feedback is unverified, nothing is escalated on one angry post alone, logs hold no feedback text,
   and the security controls are listed in SECURITY.md."

Questions to be ready for: why no LLM (cost, privacy, a 10-minute CPU limit, reproducibility); how the as-of rule is enforced (test
that later rows cannot change a week's flags, and a disguised-copy re-run); what happens at a store with few reports (shrinkage
toward the chain rate, and a flag needs two reports).

## Stores and Ask tabs (45 s)
- **Stores:** pick a store: this week vs last, weekly trend, flags and top issues with quotes. Faster than scanning a regional brief when a manager asks "what about my store?"
- **Ask:** type "How is <locality> doing?", "Any emerging issues in South?", "Who handles payment failures?" or "How accurate is this?". Say plainly: it is rule-based, no LLM, no data leaves the machine; unknown questions get an honest "I can't tell".
- **Export and keyboard:** "Download flags (CSV)" on the Emerging tab; arrow keys switch tabs; up-arrow recalls an earlier question in Ask; "Find a store" filters the store list. Responses are gzip-compressed (the script is about 3x smaller on the wire).

## Evaluation report (60 s)
Precision tab > "Open the full evaluation report". Walk it top to bottom: the precision statement; escalation precision by confidence (stricter threshold, fewer but surer); **safety recall 88.1%, the honest weak spot**; the weakest types; the worked incident flagged one week before the naive rule; reports collapsing into incidents; limits. Judges trust a team that shows its weaknesses first.
