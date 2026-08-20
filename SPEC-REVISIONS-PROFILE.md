# SPEC.md revisions — driver and team profiles

## 1. Add to the revision notes

> **Revision note 5 (20 August 2026).** Phase 3 navigation and profiles. Meeting
> navigation moved to arrows with the venue as the headline; `Meeting.sequence`
> is explicitly not a headline (§5). Results became a disclosure on the meeting
> page rather than a separate route, swapped in place with HTMX (§4.1). The
> driver and team profile is specified (§4.2). Breakdown section subtotals were
> removed so that every figure on a breakdown sums to the round total.

## 2. Add to §5, under Meeting derivation

> **`Meeting.sequence` is never surfaced as a headline.** It is derived
> bookkeeping — the API has no meeting concept — so a regrouping would renumber
> every later weekend while the round numbers stayed fixed. The venue name
> leads, round numbers give the context, and the sequence appears only in the
> weekend list, where it reads as ordering rather than as a claim.

## 3. Add as a new §4.2

### 4.2 Driver and team profile

A season-long view of one driver or team: every scoring route as a column,
every round as a row, totals in bold at the foot.

**One table, not two.** The question this screen answers is how a driver has
scored across the season, so splitting by contest would produce two grand
totals instead of one. Eleven columns fit a 360px viewport at `--step-1` in
condensed tabular figures — measured, not assumed.

    R   TP │ GRP  DW  POL │ WIN  POD  PTS  FL  ±PL

**Total points sits immediately after the round**, before the rules that
explain it, separated by a rule so it reads as their sum. Two invariants hold
and are the point of the layout: **every row's rule cells sum to its TP, and
every column's foot sums to the grand total.**

**Zeros are suppressed** to a faint mark. Nine columns of "0" is noise; a blank
is what makes the cells that fired legible at a glance, and it is what turns
eleven columns from unreadable into scannable.

**Duel wins are one column**, reading 0–3. Separate quarter-final, semi-final
and final columns would each be almost always 0 or 1 and perfectly correlated
with progression. **Places gained and lost are one signed column** — one
mechanic with a sign, where two columns would leave one always empty.

**Columns hold points, not events.** The places column shows the points the
rule awarded, not the number of places gained; the per-round breakdown carries
the underlying figure.

**Column codes carry a key** beneath the table, using the same rule names the
breakdown uses, so the vocabulary is learnt once.

A team profile is `R · car A · car B · TEAM`. Showing the halves beside the sum
makes the half-sum rule explain itself without a sentence.

**Three entry points**, all opening the profile over the current screen and
closing by dropping a URL parameter, so closing returns the picker exactly as
it was:

- an information control on each picker row
- the same control in a pick's scored breakdown
- the driver's name in a results classification

The information control is a glyph from the display face in a ruled circle,
matching the error mark's treatment. It is functional rather than decorative,
and no icon asset enters the project (§1).

**A picker row is a container with two targets**, not one link — the pick area
and the information control are siblings. A link nested inside a link is
invalid and breaks keyboard navigation.

## 4. Add to §10 Resolved

| Decision | Outcome |
|---|---|
| Meeting sequence | Bookkeeping, never a headline; venue leads, rounds give context |
| Results placement | A disclosure on the meeting page, swapped in place with HTMX |
| Breakdown subtotals | None — every figure on a breakdown sums to the round total |
| Profile layout | One wide table; TP first; zeros suppressed; duel wins one column; places one signed column |
| Profile entry points | Picker row control, breakdown control, driver name in a classification |

## 5. Add to §7, Stack row

HTMX is now in use, self-hosted at `app/static/js/htmx.min.js`. Interactive
fragments keep a working `href` alongside their `hx-get`, so the page functions
without JavaScript and HTMX enhances it. `hx-push-url` keeps the address bar in
step, so the back button and a reload both land where the reader was.
