# Formula E Fantasy — Project Spec

**Status:** Phase 0 complete and deployed. Phase 1 complete — Season 12 backfilled locally.
**Last updated:** 19 August 2026
**Target:** Live before the Season 13 opener — Jeddah, 18–19 December 2026
**Domain:** `fe.kitsniff.com`

> **Revision note 1 (18 Aug 2026).** Implementation-planning session. Places gained/lost ships in v1 (§3); forced team relocation costs two transfers, spent atomically (§2); Season 13 sporting format changes recorded (§3, §6, Appendix A); `Round.format` added (§5); design ground fixed as light with open-licence typography (§1); config split and CSS-native design tokens (§7); auth-lift divergences recorded (§7); repo structure added (§12); Phase 0 broken down with checkpoints (§8).

> **Revision note 2 (18 Aug 2026).** Phase 0 shipped; Phase 1 stage 1 built. The API differs from the original probe write-up in nine material ways — see §6 and Appendix A. Two of them (`session.type` having four values, and qualifying rows omitting `points`/`status` rather than nulling them) would have crashed a parser written to the old spec. Also: sync conflict policy defined (§6); production proxy and session findings recorded (§7); Postgres version claim corrected (§7); fixture inventory expanded (Appendix A).

> **Revision note 3 (19 Aug 2026).** Phase 1 complete: provider client, ingestion schema, season sync and results backfill. Season 12 is fully ingested locally — 11 meetings, 17 rounds, 187 sessions, 880 result rows. **§3's fastest-lap rule is corrected: derive it from the minimum `lap_time`, not from `fastestLap.rank`, which encodes Formula E's top-ten restriction and disagrees on eight of seventeen S12 rounds.** Also: `gridPosition` is the post-penalty starting slot, not the qualifying result (Appendix A); the provider rate-limits at roughly two requests per second (§6); practice and `other` sessions are never ingested (§6); Phase 2 splits into engine then simulation (§8, §9).

---

## 1. Concept

A fantasy team game for the ABB FIA Formula E World Championship, built for a small friend group. Each player picks **4 drivers + 1 team**. Those five picks earn points from real race weekend performance. One transfer per meeting, bankable up to two.

Companion to the existing F1 Predictions app (`f1.kitsniff.com`) but a separate, standalone application.

### Why fantasy rather than predictions

- **Graceful degradation.** Season 13 runs 18 December – 25 July: eight months, 13 meetings. A player who forgets the app for a month still scores. A predictions app returns zeros and loses them permanently. For a casual group over a long season, this single property outweighs everything else.
- **Inherently social.** League tables and comparing lineups are the point, not a bolt-on.
- **Clearer scope.** Fantasy games have a known shape and a definition of done.
- **Richer data to present.** Five picks × ~7 scoring routes × 21 races × 13 meetings, plus transfer history and dream-team comparison — a far better canvas than five booleans per round.

### Design values

The real goal of this project is learning UI, UX, and the clear, beautiful presentation of dense structured data.

- Minimal, clean, engaging — but clarity beats minimalism when data is dense
- Genuinely unique; must not read as generically generated
- **Avoid "AI-flag" patterns:** hero graphics, pill-shaped tags, gradient shading, decorative iconography
- Typography and layout do the work that colour and decoration would otherwise do
- No reuse of the F1 app's parchment/moss language — clean-sheet visual exercise
- This explicitly retires the pill component used throughout the F1 app

**Ground: light.** Deliberately contrary to Formula E's own very dark brand identity, and contrary to the default look of a motorsport data app. A light ground also makes the negative values in places-lost scoring easier to render legibly without resorting to alarm-red fills.

**Typography: open licence only.** No paid font licences. The typeface choice is the highest-leverage decision in the visual language, since typography is carrying the load that colour and decoration normally would. Settled in Phase 3, not before.

**Design tokens live in CSS, not Python.** Colour, spacing, and type scale belong in `static/css/tokens.css` as custom properties. The F1 app's approach — a `PALETTE` dict in `config.py` injected into Jinja — makes every colour tweak a Python edit and a redeploy, and blocks `color-mix()`, `light-dark()`, and relative colour syntax. Do not repeat it.

**Typography** Archivo (OFL, variable, wght 100–900 / wdth 62–125) for all text and data. Anybody (OFL, variable) for display only, at width 100 and weight 700. Anybody's scope is round numbers, meeting mastheads, and pick or lineup totals — nothing else, never below 20px, never in a table cell. Both self-hosted and subset to Latin Extended; no font CDN.

**Scale in rem**, data size 13px equivalent. Form inputs are pinned at 16px, because iOS Safari zooms the viewport on a smaller focused input.

**No accent colour in v1**. Personal marking ("this is yours") is structural — full ink, heavier weight, and a rule in a reserved gutter. Team hue is the only chroma on the page.

**Team colour is two stripes**, seeded from team.color for hue only; lightness and chroma come from tokens.css and are routed by hue to one of two clamp tiers, because yellows and cyans cannot hold chroma at the lightness reds and purples can. The secondary stripe carries a second, independent channel: solid, tint, dark, or light. Seeds and overrides live in app/palette.py — data repair, not design. An unseeded team degrades to a neutral rule.

### Viewport strategy

**Mobile-first, with desktop treated as a wide tablet** — a constrained, centred column that expands moderately rather than a sprawling multi-panel layout.

This aligns usefully with the anti-AI-flag goal: grids of cards spanning a 1440px viewport are precisely the generated-dashboard look being avoided. A constrained measure forces typographic hierarchy to carry the information load.

**Known design challenge:** the qualifying bracket is inherently horizontal — 8 drivers → 4 quarter-finals → 2 semis → 1 final. That does not fit a phone-width column as a conventional left-to-right tree. It likely needs a genuinely different representation on narrow viewports (vertical progression, or stage-by-stage) rather than a scaled-down tree. **This is the hardest visual problem in the project and the most interesting one.** Solve it at mobile width first; the desktop version is then a relaxation, not a reflow.

---

## 2. Game rules

### Lineup

**4 drivers + 1 team**, subject to:

1. Maximum one driver per team among the four driver picks
2. The team pick must not be a team already represented in the driver picks

With **20 drivers across 10 teams** (verified from the S12 season payload), that is C(10,4) × 2⁴ × 6 = **20,160 valid lineups**. Each player covers 5 of 10 teams — half the grid — so overlap on obvious picks is expected. Differentiation comes mainly from transfer timing.

**Do not hard-code 20 drivers or 10 teams.** That figure is a property of the current grid, not an invariant. Gen4 could bring an eleventh team, a third car, or a mid-season withdrawal. Constraint validation and the dream-team brute force must operate over the actual roster derived from data. Treat 20,160 as a performance expectation only.

**Which team a driver belongs to is a per-round question**, answered by `SeatEntry.covers_round()`. A mid-season transfer produces two seat entries with disjoint round arrays, so the one-driver-per-team constraint stays correct across a switch. Season 12 contained no switches, so this path has only been exercised by tests — expect it to meet reality for the first time in Season 13.

### Transfers

- **1 transfer per meeting** (not per round)
- Unused transfers bank, to a **maximum of 2 available**
- A transfer swaps one driver for another driver, or the team for another team
- All lineup constraints must hold after every transfer
- Two banked transfers allow a same-meeting driver-out/team-in swap for the same constructor

Meeting-level transfers (rather than per-round) mean no turnaround on the single day between races of a double-header.

**Emergent strategy:** double-header meetings score twice on one lineup, so banking a transfer for Berlin or Monaco is genuinely tactical. Good depth from a simple rule.

#### Transfer cost — the counting rule

**Cost = the number of changed slots between consecutive lineup snapshots.** Five slots (four drivers, one team); count how many differ; that is the cost. Nothing more sophisticated.

**Forced team relocation costs two transfers, spent atomically.** Worked example: your drivers are from teams A, B, C, D and your team pick is E. You want to bring in a driver from team E. That collides with constraint 2, so the team pick must move as well. Two slots change, so the cost is 2. The player must have banked two transfers before the move is available at all — there is no partial version, and no "free" forced move.

Rationale: it is consistent with the existing rule that two banked transfers buy a driver-out/team-in swap for the same constructor, it needs no special case in the diff, and it keeps the bank trivially derivable from snapshots. It also makes team-slot placement a genuine planning decision rather than an afterthought.

**Consequence for the UI: the lineup editor is a staged draft with an explicit commit.** There is no legal intermediate state between "team E driver in" and "team E out of the team slot", so edits cannot be applied slot-by-slot against the server. The editor holds a draft lineup client-side, shows live constraint validation and a running transfer cost, and writes a single snapshot on commit. Validate the same rules server-side on submit; the client-side check is convenience, never authority.

### Deadline

Lineup locks at the **first qualifying session of the meeting's first round**. One deadline per meeting.

Computed from the earliest `startTime` across the sessions of `type: "qualifying"` on the meeting's first round. Note that session times come from the events endpoint only — the season detail endpoint returns the calendar without them (§6).

**Store the computed deadline on the Meeting; do not derive it at request time.** Formula E schedules move. The deadline is computed at season sync, then persisted, along with `deadline_session_id` so the UI can name the session rather than showing a bare timestamp.

**The deadline is monotonic once published: a resync may move it later, never earlier.** Without this rule a schedule shift retroactively locks players out of a meeting they were still editing, with no way to explain what happened. An earlier session time found at resync is a sync conflict (§6): the meeting is left untouched and flagged.

### Season-start grace

Unlimited free lineup edits until the **first deadline of the season** (Jeddah, 18 December 2026). Transfer accounting begins from meeting 2. A player who joins later gets the same unlimited-edit grace up to their first locked deadline.

### Absent drivers

A picked driver who does not appear in a session's results scores 0 for it. No substitution, no compensation.

If a driver leaves the grid mid-season (injury, contract change), the player must spend a normal transfer to replace them. **No free transfers**, deliberately: it avoids a special case, and it removes any route where a convenient absence hands someone an extra move.

**The roster is fully derived from API data.** No curated entry list, no admin-maintained "main driver" flag. One-off reserve drivers become pickable, and that is acceptable — the app must not assert who the regular drivers are, because it would eventually be wrong.

**Mitigation against misinforming users:** the driver picker shows rounds-participated alongside each driver, taken directly from `driver.teams[].participationRounds` (§6). A reserve who has appeared once is then self-evidently a one-off without the app claiming anything.

**Pickable drivers come from seat entries, not results.** A driver appearing only in a rookie practice session has no seat entry and is therefore not pickable, which is the correct outcome — see the note on ingested stages in §6.

### Leagues

**Invite-based, multi-league** — built for medium-scale production, not just the initial friend group.

- Users may belong to multiple leagues simultaneously
- Leagues are created by a user, who becomes its admin
- Joining is by invite link or code
- Per-league member caps (as in the F1 app) to bound query cost
- A global/site-wide table is possible later, but leagues are the primary social unit

A single lineup per user per meeting scores into **every** league they belong to — league membership is a view over scores, never a separate scoring context. This keeps scoring O(users) rather than O(users × leagues).

**Leagues are durable across seasons.** A League row carries no `season_id`; season scoping applies to the standings computed over it. League administration lives on the membership row (a `role` column), not solely on `League.created_by_id`, so a league survives its creator deleting their account. See §7.

### Lineup visibility

**Hidden until lock.** A player's lineup for a meeting is private until that meeting's deadline passes, then visible to co-members of their leagues.

**Enforce server-side**, in the query layer — not by hiding fields in a template. A locked/unlocked check that lives only in Jinja will leak through any JSON endpoint, HTMX partial, or friend-profile route added later.

Consequences: friend profiles show only locked meetings; the dream team appears only once results are in; and no pre-deadline "who picked what" view exists at all, which removes copying as a strategy.

---

## 3. Scoring

Scored **per round**. A double-header meeting scores twice on the same lineup.

> **Note on Season 13.** From 2026/27, Formula E awards real championship points in qualifying, on a sliding scale to the eight drivers who reach the Duels. This changes nothing about the fantasy scoring below — it is a separate points system — but it does affect the ingest sanity check. See §6.

### Qualifying

| Event | Points |
|---|---|
| Progress out of the group stage (top 4 of each group → 8 drivers) | 2 |
| Each head-to-head duel win (quarter-final, semi-final, final) | 1 each |
| Pole position | 3 |

Resulting gradient:

| Outcome | Total |
|---|---|
| Pole | **8** |
| Lost the final | 4 |
| Lost a semi-final | 3 |
| Lost a quarter-final | 2 |
| Eliminated in group | 0 |

Total qualifying points distributed per round across the whole field: 16 (groups) + 7 (duels) + 3 (pole) = 26.

**Pole is the Qual Final winner, not whoever starts P1.** Grid penalties move drivers back while they keep the qualifying result — Wehrlein took pole at São Paulo and started P4. Derive pole from the Qual Final classification; never from `gridPosition`.

### Race

| Event | Points |
|---|---|
| Race win | 5 |
| Podium finish | 5 |
| Points finish (top 10) | 2 |
| Fastest lap | 1 |
| Every 5 places gained (grid → finish) | +2, capped at **+4** |
| Every 5 places lost | −2, capped at **−4** |

**These stack.** A win is 5 + 5 + 2 = 12 before places gained and fastest lap.

Race ceiling: 17 (win from P20 with fastest lap). Roughly double the qualifying ceiling of 8 — deliberate; this is a racing game.

#### Fastest lap — derive from `lap_time`, not `fastestLap.rank`

**Corrected 19 August 2026.** The fantasy fastest-lap point is **unconditional**: it goes to whoever set the quickest lap of the race, regardless of finishing position. Formula E's own championship point applies only inside the top ten; this game deliberately does not.

An earlier draft instructed deriving the point from `fastestLap.rank == 1`. That is wrong. **`fastestLap.rank` marks the fastest lap among championship-eligible drivers**, so it silently reimposes the top-ten restriction. Measured across Season 12, it disagrees with the quickest `lap_time` on **eight of seventeen rounds**, and in seven of those eight the genuinely quickest driver finished outside the top ten (P19, P12, P12, P19, P18, P19, P16, P16).

The eighth, Shanghai R13, is a straightforward vendor error: Rowland (P8, 1:10.945) set the quickest lap and the `points` field credits him, but `rank` marks Vergne (P2, 1:11.394). Both were inside the top ten, so eligibility does not explain it.

So: **the fastest-lap point goes to the driver with the minimum `lap_time` across the race classification.** Store `fastestLap.rank` for reference; never score from it.

Implementation caution: `lap_time` is a string (`"1:10.945"`). Comparing as strings happens to work only because every Formula E lap is a single-digit minute. Parse to a duration.

### Worked examples

| Scenario | Breakdown | Total |
|---|---|---|
| Pole, wins from P1, sets FL | Quali 8 + win 5 + podium 5 + points 2 + FL 1 + places 0 | **21** |
| Wins from P6, group exit | 5 + 5 + 2 + places gained 2 | **14** |
| Pole, retires (classified ~P18) | Quali 8 + places lost −4 | **4** |
| P4 quali, finishes P3 | Quali 3 + podium 5 + points 2 | **10** |
| P20 quali, finishes P11 | Places gained +2 | **2** |

These are the acceptance cases for the scoring engine.

### Places gained / lost — ships in v1

**Reversal of an earlier decision.** A previous draft of this spec deferred places gained/lost past v1 under a "ship with less" principle. That was wrong, for a specific reason: without it, race scoring has no midfield resolution at all.

Strip the rule out and the race gradient becomes P1 = 12, P2–P3 = 7, **P4–P10 = 2**, P11–P20 = 0. Seven consecutive finishing positions score identically. Most picks land in that band most weekends, the dream team ties constantly, and a P4 drive is indistinguishable from a P10 drive. Places gained/lost is the only rule that resolves the middle of the field, so it is not an optional extra — it is load-bearing.

Structurally asymmetric by design: a front-row qualifier has no upside and up to −4 exposure, a back-row qualifier has +4 upside and no risk. This is the main tension in lineup choice and partly counterbalances the value of strong qualifiers.

**Grid position means the starting slot, after penalties.** That is what this rule wants: a driver serving a five-place penalty genuinely starts further back and genuinely has more to gain. Do not substitute the qualifying result.

**DNFs punish themselves.** The API gives retirements ranked finishing positions (São Paulo's seven DNFs occupied P14–P20), so a retiring front-runner automatically takes the full −4. No separate DNF rule needed.

**Defensive handling.** If `gridPosition` is null or zero on a race result row (pit-lane start, data gap), score places gained/lost as 0 for that driver and log a warning. Never guess a grid slot. The ingest already emits this warning at load time.

**Magnitudes are provisional at ±4** and are the primary output of the S12 simulation (§9). See the caveat there about sprint races.

### Team scoring

**Half the sum of the team's two drivers' round scores**, including any negative places-lost values.

Keeps the team slot comparable in value to a driver slot, and creates a distinct judgement: you want a team whose *both* cars perform, which is a different call from picking one star.

Halves are permitted (drivers on 8 and 3 → team scores 5.5). Store as decimal; do not round, as rounding introduces a bias that needs explaining.

### Scoring rulesets are versioned and snapshotted

Point values are not constants in code. They live in `app/scoring/rules.py` as a named, versioned ruleset, and the ruleset in force is recorded against each Round when the round is created — already implemented as `Round.scoring_ruleset_version`.

This is lifted from the F1 app's `round_scoring_config` pattern, and this project needs it more: §9 exists specifically to tune point values against real data, and the ±4 cap is explicitly provisional. Changing a value must never retroactively rewrite a completed round's score. Combined with the stored per-pick breakdown (§5), every historical score stays reproducible and rescoring stays idempotent.

---

## 4. Views

- **Lineup** — pick and manage the five slots; staged draft with explicit commit; transfer state, bank, and the running cost of the current draft clearly shown; rounds-participated shown per driver in the picker
- **Meeting view** — points earned, split into clearly headed sections labelled by round format (`E-Prix Unleashed` / `E-Prix`), not "Race 1 / Race 2"
- **Points breakdown** — per pick, per race, showing exactly which rules fired. The core data-presentation challenge, and the main design opportunity. Real ranges from S12: a driver-round scores −4 to 21 across up to seven
  simultaneous rules; season totals ran 8 to 104. The dream team occasionally
  ties — show "tied with 17 others" rather than implying a single answer.
- **Dream team** — the highest-scoring valid lineup for each round, brute-forced across the actual roster (~20,160 combinations at current grid size — instant, no optimisation needed). A star marks any user pick that made it.
- **League table** — season standings within a league
- **Friend profile** — another player's season: lineups and points by meeting
- **Results with personal highlighting** — the qualifying bracket and race classification with the user's own picks marked. Personal stakes make the visualisation compelling in a way a neutral bracket is not.

---

## 5. Domain model

Three levels. The API has no meeting concept — it treats each race as a top-level "event" — so Meeting is derived.

```
Meeting    e.g. London          11 in S12, 13 in S13   ← user-facing chronology, transfer/deadline unit
  Round    R16, R17             17 in S12, 21 in S13   ← FE numbering, scoring unit
    Session  groups/duels/race  ~11 per round          ← ingestion only
```

**Naming:** `Meeting` internally, "Weekend" in the UI. **Do not use "event"** in the domain model — the API already uses it for a single race.

**Meeting derivation:** group *consecutive* events by `location.id` plus date adjacency (default window 3 days) within a season. **Never group by `name`** — sponsors are baked in ("2026 Hankook London E-Prix" vs "2025 Marvel Fantastic Four London E-Prix"). Store a clean display name ("London") separately, taken from `location.city`.

Consecutiveness matters: it is what stops two separate visits to the same circuit in one season collapsing into a single weekend.

Derived automatically at season sync with admin confirm/override (`Meeting.grouping_locked`). Verified against the real S12 calendar: 17 events resolve to 11 meetings with six double-headers, and Sanya and Shanghai correctly stay separate.

`location.id` is stable across seasons, enabling multi-season location records.

### Round numbering

**Not in the payload.** There is no round field anywhere in the API. Round numbers are inferred from position within `season_detail.schedule`, which is also what the provider's `participationRounds` arrays refer to — so calendar order is used as given rather than re-sorted by date, since re-sorting would desynchronise the two.

Once assigned, a round number is immutable: a resync that would renumber an existing round raises a sync conflict rather than updating.

### Round format — new for Season 13

`Round.format` with values `eprix` and `eprix_unleashed`.

Derived at sync by rule: a single-header meeting's only round is `eprix`; in a double-header, round 1 is `eprix_unleashed` and round 2 is `eprix`. **Admin-overridable via `Round.format_locked`** — the regulations say double-headers "typically" carry one of each, and typically is not always.

**Gated on season.** The rule applies from Season 13 (ending year 2027) onward. Season 12 ran two identical races per double-header, so applying it to the backfill would label half the calendar as sprints that never happened — and the §9 simulation would then draw format-aware conclusions from fiction.

### Session stage

`Session.stage` and `Session.stage_index` are stored separately: "Qual Quarter-Final 3" becomes `stage="quarter_final", stage_index=3`, derived once at ingest from the session name.

Splitting them means a reshaped bracket — Formula E ran four qualifying groups before 2022 — is a data change rather than a migration. It also means the scoring engine never re-parses a session name.

### Lineups: store snapshots, not deltas

**The most important architectural decision in this project.**

Store a **complete lineup snapshot per (user, meeting)**. Treat the transfer allowance as a *validation rule* between consecutive snapshots, not as the stored truth.

Rationale: with a transfer bank, a lineup at meeting 8 is otherwise only knowable by replaying meetings 1–7. Replaying a sequence to fix a scoring bug in March is fragile. With snapshots, every meeting is independently recomputable, the transfer bank is derivable, and a season history is a straight query.

Transfer cost between consecutive snapshots is the count of changed slots (§2). That is the whole derivation.

### Scores

Store computed points per `(user, meeting, round, pick)` with the rule breakdown and the scoring ruleset version, so the points-breakdown view is a read rather than a recomputation, and rescoring is idempotent.

---

## 6. Data source

**Provider:** Orange Cat Blacktop — `https://api.ocblacktop.com/v1/formula-e`
**Auth:** `x-api-key` header
**Tier:** Free — 7,500 requests/month, server-side only, non-commercial
**Live data:** None. Results written after each session completes.

### Critical: User-Agent required

Default `Python-urllib/3.x` is blocked by Cloudflare with **Error 1010** (403) before reaching the API. A descriptive UA works:

```
KitsniffFEFantasy/0.1.0 (+https://fe.kitsniff.com)
```

Set the UA centrally and validate it at construction — `OCBlacktopProvider` refuses a `Python-*` UA outright, so the failure surfaces immediately rather than as a 403 inside a worker log.

A 403 is ambiguous and must be classified: an HTML body naming error 1010 is a CDN refusal (`ProviderBlockedError`), a JSON body is an API credential failure (`ProviderAuthError`). Treating a CDN block as bad credentials sends you looking for a key problem that does not exist.

**Risk:** a CDN blocking a plain server-side client on a tier documented as server-side-only is a reliability warning sign. **Mitigation: provider abstraction layer from day one** (`app/providers/`, see §12) — implemented, with `base.py` defining normalised dataclasses and a `ResultsProvider` protocol so nothing downstream sees a vendor payload.

### Rate limiting — undocumented, real

The free tier returns **HTTP 429 at roughly two sustained requests per second**. Nothing in the documentation mentions it; it surfaced during the S12 backfill, where five sessions failed after exhausting their retries.

Handling, implemented:

- `OCB_MIN_REQUEST_INTERVAL_SECONDS` throttles the steady rate. **1.0 is the working value**; 0.5 triggers 429s during a long run.
- A 429 backs off far longer than a transient 5xx — 15 seconds scaled by attempt — because retrying in one second simply spends another call against the same window.
- `Retry-After` is honoured when present.
- A failed session is never stamped `results_ingested_at`, so re-running the backfill retries exactly the failures and skips everything already stored.

**The live results poller must respect this**, since it runs when it matters most.

### Verified quirks

Probed 14 August 2026; corrected and extended 18–19 August 2026 against a re-fetched corpus and a full Season 12 ingest. **Where an earlier draft of this section said otherwise, this table is right.**

| Quirk | Detail |
|---|---|
| Three envelope styles | `/events` → `{data, meta}`; `/seasons/{id}` → bare object; `/results` → bare array. Normalised in the client layer. |
| Unknown params silently ignored | `?season=`, `?seasonId=`, `?perPage=` return **byte-identical** unfiltered responses with HTTP 200 — verified by hash. **Never treat a 200 as proof a filter applied.** Only `limit` and `page` work. |
| The events collection cannot be filtered | 165 events across all 12 seasons, with no server-side season filter. A season's session times require paging the whole collection and matching client-side against the event IDs from season detail. Four calls at `limit=50`. **Season sync is inherently a two-step operation.** |
| Pagination | `?limit=` and `?page=` work. `meta` = `{page, limit, total, totalPages}`. Default limit 20. |
| Seasons UUID-keyed | `/seasons/2026` → 400 "uuid is expected". `/seasons` gives the year → UUID index. |
| **Season `year` is the ENDING year** | S12 ran Dec 2025 – Aug 2026 and is keyed **2026**. S13 runs Dec 2026 – Jul 2027 and will be keyed **2027**. Reading it as the starting year silently returns the wrong season, because the payload is valid either way. |
| **Season 13 not yet published** | `/seasons` runs 2026 back to 2015 as of 19 Aug 2026. `status` and `roundCount` are null for every season, so year is the only usable selector. Resolve by year at run time and treat "not found" as a normal condition. |
| **`session.type` has four values** | `practice`, `qualifying`, `race`, **`other`**. Confirmed in real data: Season 12 round 3 carries a "Rookie Free Practice" typed `other`. Season 13's shakedown day will most likely arrive the same way. |
| **Sessions use `startTime`/`endTime`** | Events use `dateStart`/`dateEnd`. The two levels use opposite naming conventions; reading the event's names at session level yields a null deadline. |
| Sessions carry their own status | `scheduled` \| `ongoing` \| `completed`. Checked before requesting results, so a scheduled session costs no call. |
| **Qualifying rows omit `points` and `status`** | Absent keys, not null ones — subscripting raises `KeyError` on nine of the eleven sessions in a round. `gridPosition` by contrast is present-and-null there. Read every field with `.get()`. |
| **`driver.code` is null for 16 of 20** | Not "frequently" — almost always. There is no code-based display path; **key on `driver.id` (UUID)**, label with `lastName` plus `number`, treat `code` as decoration. |
| **`gridPosition` is the post-penalty starting slot** | NOT the qualifying result. Wehrlein took pole at São Paulo and started P4. Correct for places gained/lost; wrong for anything asking "who took pole". |
| **`fastestLap.rank` is eligibility-restricted** | Marks the fastest lap among top-ten finishers, not of the race. Disagrees with the quickest `lap_time` on 8 of 17 S12 rounds. Store it; never score from it (§3). |
| Type inconsistency | `position` is a string (`"1"`), `gridPosition` an int (`5`), `points` a string decimal. Cast on ingest. |
| **`displayTime` has a variable shape** | `"1:01:13.217"` for a race over an hour, `"59:23.013"` for one under. Never split on `:` expecting three parts — the 30-minute E-Prix Unleashed will be sub-hour every time. |
| `team.color` unreliable | Andretti and Jaguar both `000000`; Nissan has a real value. Not a usable palette. |
| Season detail lacks sessions | `/seasons/{uuid}` gives calendar + standings but no session times. Those come only from `/events`. |

### Endpoint strategy

- **`/seasons`** — year → UUID index. Resolve the season by ending year.
- **`/seasons/{uuid}`** — full calendar plus driver and team standings in one 13.7KB call.
- **`/events?limit=50&page=N`** — session times and IDs (`schedule[]` embedded per event). Filter client-side.
- **`/events/{id}/sessions/{id}/results`** — per session.

**Only qualifying and race sessions are ingested.** Practice teaches the game nothing, and `other` covers cases like Season 12's Rookie Free Practice — a session full of drivers who are not on the grid. Ingesting it would put test drivers in the results table and corrupt any "who raced this round" query. Ten calls per round rather than eleven.

**Quota:** ~10 sessions × 21 rounds ≈ 210 calls/season for full capture, plus 4–9 for the calendar join. Comfortably inside the free tier — but the results-polling worker is the real consumer. Bound polling to windows following a session's scheduled end, check session `status` first, back off, and stop on success.

### `participationRounds` — corrected

It lives **inside `driver.teams[]`**, not at driver level, and it is an **array of round numbers**, not a count:

```json
"teams": [{"id": "...", "name": "PORSCHE...", "participationRounds": [1, 2, ..., 17]}]
```

Two consequences. Being per-team, a mid-season driver switch is represented correctly — two entries with disjoint round arrays. And because it is exactly "rounds actually raced", **it is the source for the driver picker's rounds-participated figure**; the earlier instruction to compute this ourselves from results is unnecessary.

It remains a live counter that grows during a season: the 14 August probe showed 15 rounds against a 17-event schedule because London had not yet run; the re-fetch after the finale shows 17. **So it is still not roster truth** — a driver who has not yet raced has an empty array. Use it for display, never to decide who is on the grid.

### Sync conflict policy

A resync must be trustworthy enough to run unattended twice a day, and must never half-apply. So changes are classified, and **each meeting syncs in its own transaction**.

**Applied silently:** a new event appearing, a meeting gaining a round, a session time moving later, a name or status change, a result arriving.

**Skipped and flagged:** a deadline that would move earlier (the monotonic rule in §2), a meeting losing a round, a round moving between meetings, a round being renumbered, a session count that does not match the expected bracket shape on a *completed* round, an unrecognised qualifying session name.

A meeting *gaining* a round is deliberately safe: it is just a new event appearing, and flagging it would make every legitimate calendar addition a conflict. The bracket-shape check is limited to completed rounds because a future round routinely has a partial schedule, and flagging that twice a day would train you to ignore the conflicts page.

An unsafe change rolls back that meeting untouched and records a `SyncConflict` row; the remaining meetings apply normally. Conflicts deduplicate on a fingerprint, unique among unresolved rows, so a repeat bumps `occurrences` rather than inserting. The admin page lists outstanding conflicts; a clean run shows nothing.

### Payload sanity check

A completed session returning a partial classification is the failure worth catching: nothing errors, the rows land, and a driver quietly scores zero for a race they finished. The check compares the provider's own `points` against the published championship distribution.

Reported as **warnings, not refusals** — a mismatch means the data is worth a look, not that it should be discarded. If more than half the field disagrees, it reports that the expectation itself may be wrong rather than listing twenty complaints.

Pole detection for the check uses the **Qual Final winner**, not `gridPosition`. Sessions are ingested in schedule order, so the final has landed by the time the race is fetched. When the pole sitter is unknown the check accepts either total rather than inventing a complaint.

**Season-scoped**: it is skipped from Season 13, where qualifying awards championship points on a sliding scale and no replacement expectation exists yet.

Run against Season 12, the check surfaced exactly two real discrepancies across ~340 race rows — both at Shanghai R13, both traceable to the `fastestLap.rank` error in §3.

### Data quality

Cross-validation passed. At Tokyo R2, points matched finishing order; Dennis's 16 for P3 confirmed the +1 fastest lap bonus; Mortara's 3.0 from a P18 DNF matched his Qual Final win and `gridPosition: 1`. Qualifying and race payloads agree.

Season 12 as ingested: 11 meetings, 17 rounds, 187 sessions, 880 result rows, 20 drivers, 10 teams, 20 seat entries, zero sync conflicts.

**Action:** spot-check driver–team pairings against a trusted source. Small vendors get lineups wrong; Cassidy at Citroën is worth an eyeball.

### Season 13 sporting changes — effect on ingest

Announced June 2026 for the Gen4 era. Three things matter here.

1. **Qualifying now awards championship points.** The top eight — those reaching the Duels — score on a sliding scale, up to roughly 105 points across the season's 21 qualifying sessions. **This breaks the Appendix A ingest sanity check**, which assumes qualifying contributes only a 3-point pole bonus to the race-row `points` field. The check is already gated on season; write a replacement expectation once a real payload is available.
2. **Double-headers run two different race formats.** Race 1 is `E-Prix Unleashed` (30 minutes, high downforce, no Pit Boost, six-minute attack mode); race 2 is a standard `E-Prix` (45 minutes, with Pit Boost). See `Round.format` in §5.
3. **A shakedown day precedes each weekend.** Expect unfamiliar entries in `schedule[]`, most likely with `type: "other"`. The parser fails loudly only on unrecognised *qualifying* session names (Appendix A); anything else is recorded as `other` and ignored.

Calendar facts for S13: 21 races across 13 locations, eight double-headers (Jeddah, Monaco, Berlin, Zandvoort, Brands Hatch, Jarama, Shanghai, Tokyo), new venues at COTA, Zandvoort and Brands Hatch, Miami returning. **The calendar is not frozen** — Mexico City is the stated fallback opener if Jeddah is judged unsafe. Do not treat the sync as a one-time operation.

---

## 7. Infrastructure

| Item | Decision |
|---|---|
| Domain | `fe.kitsniff.com` via Cloudflare CNAME |
| Hosting | **Separate** Railway project with its own Postgres instance (fourth project on the account) |
| Repo | Fresh repo, not a fork of `f1-predictions` |
| Local dev | Raspberry Pi (Singularity), Debian 12, `~/projects/fe-fantasy` |
| Python | **3.11.2** — no PEP 695 generics, no `type` statement, no 3.12+ syntax. Pinned for Nixpacks via `.python-version`. |
| Postgres | **18.x in both environments** — local 18.4, Railway 18.6 and patched on their schedule. Same major version, so `pg_dump` restores in both directions; minor versions will drift. |
| DB driver | **psycopg 3** (`psycopg[binary]`), URI scheme `postgresql+psycopg://`. Not psycopg2. |
| Auth | Separate account system. Keep the `User` model shape close to the F1 app so a future merge or SSO handshake stays cheap. |
| Stack | Flask, SQLAlchemy 2.x, Alembic/Flask-Migrate, APScheduler, HTMX, Jinja2, Flask-WTF, Gunicorn, pytest |
| Email | Resend, **password reset only**. No deadline reminders, no digests, no notifications of any kind. |
| Season scoping | `season_id` on every season-scoped table from day one. Leagues are the exception — they are durable across seasons; scoping applies to standings computed over them. |

**Consequence of the no-email policy:** all engagement pressure sits in the interface. The deadline state, unused transfer count, and "your lineup is unchanged since last meeting" condition need to be prominent on first load — there is no external nudge. This is workable precisely because the fantasy model degrades gracefully: a forgotten meeting still scores, so a missed reminder is not a lost player.

### Deployment notes (learned in Phase 0)

- **Migrations run as a Railway pre-deploy command** (`flask db upgrade`), not from application startup. Startup migration races across gunicorn workers, and a failure there puts a container with the wrong schema in front of traffic. Pre-deploy runs once and aborts the deploy on failure.
- **Healthcheck path is `/health`**, set in `railway.toml` and in the service settings. Without it a deploy that boots but cannot reach Postgres reports "online".
- **Cloudflare SSL/TLS must be Full (strict).** Flexible sends plaintext to Railway, so `SESSION_COOKIE_SECURE` cookies never return and login silently fails to persist — which presents as an auth bug, not a TLS setting.
- **The Railway-generated `*.up.railway.app` domain is deleted** once the custom domain works. `CF-Connecting-IP` is only trustworthy for traffic that passed through Cloudflare, so leaving the direct route open lets anyone forge their own rate-limit key.
- **`DATABASE_PUBLIC_URL` requires enabling the TCP proxy** on the Postgres service; new Railway Postgres instances are private-only by default. `DATABASE_URL` (private) stays as the application's variable — no egress cost, lower latency.
- **Railway can silently disconnect from GitHub.** Auto-deploy stopped once with an "upstream repo" set and the trigger disabled. If a push does not deploy, check Settings → Source before debugging anything else.
- Production refuses to boot on a default `SECRET_KEY`, an unset `DATABASE_URL`, or a non-https `APP_BASE_URL`. A first-deploy crash loop showing `ConfigError` is that check working; the message names the variable.

### Lifting from the F1 app

**Lift largely as-is:** `User` and `PasswordResetToken` models, auth blueprint (routes, forms, Resend email module), login rate limiting, `_is_safe_redirect`, CSRF patterns, ProxyFix, `/health`, Alembic `env.py`, `League` and `LeagueMembership`, invite landing and pending-invite session handling, worker polling with grace-period fallback, the `APP_VERSION`-in-User-Agent pattern, the per-round scoring config snapshot.

**Do not lift:** wildcards, H2H predictions, heatmaps, specials bank, pit-stop ingestion, F1 points scoring, the `PALETTE` and `HEATMAP_COLORS` config blocks, templates of any kind.

**Divergences from the F1 implementation, deliberate:**

| Change | Reason |
|---|---|
| Drop `User.is_contributor` | F1-specific, tied to a blueprint this app does not have |
| Add `User.last_seen_at` | "Active in the last 30 days" cannot come from `last_login_at`: with remember-me sessions a user can be active daily for months without a login event. Updated once per calendar day per user by a before_request hook. |
| `League.created_by_id` nullable, `ondelete="SET NULL"`; `role` column on `LeagueMembership` | In the F1 app the FK is `RESTRICT` and `NOT NULL`, so any user who has created a league gets an unhandled `IntegrityError` on account deletion. **This is a live bug in the F1 app and worth patching there too.** |
| Add rate limiting to `/register` | The F1 app limits login and the invite landing but leaves public registration open |
| **Client IP from `CF-Connecting-IP`, not `request.remote_addr`** | Railway's edge rebuilds `X-Forwarded-For` from its own peer address, so the chain reads `<cloudflare-edge>, <railway-edge>` and the client never appears in it. No `ProxyFix` hop count can recover it. Verified in production via `/admin/request-info`. Only rate limiting depends on this, and before the fix every visitor shared one bucket. |
| **`session_protection = "basic"`, not `"strong"`** | `"strong"` pins a session to `request.remote_addr`, which here is a rotating Cloudflare edge address — a hard refresh landed on a different edge and logged the user out. Also wrong on principle for a mobile-first app: a phone moving between wifi and mobile data changes IP mid-session. |
| Split `config.py` | The F1 config is four concerns in one file. Here: `app/config.py` for environment only, `app/scoring/rules.py` for point values (importable without Flask), CSS custom properties for design tokens |
| SQLAlchemy 2.x `select()` throughout | The F1 app passes a Flask-SQLAlchemy `Query` into `session.execute()`, which is deprecated and slated for removal. Same pattern exists in the F1 `forms.py` and will break on a future bump. |
| Fresh dependency pins, psycopg 3 | The F1 pins date from mid-2024 |
| Dev dependencies split into `requirements-dev.txt` | pytest and responses were otherwise shipping into the production image |
| Drop `pytest-flask` | Adds little over a plain app fixture in `conftest.py` |
| Add `responses` | For mocking the OCB API in tests against the committed probe fixtures |

**Known limitation, accepted:** login rate limiting is in-memory and therefore per-process. With `gunicorn --workers 2` the effective allowance doubles and blocking is inconsistent between requests. Acceptable for an invite-scale app; revisit with a `login_attempts` table if the app is ever shared publicly.

**Known limitation, accepted:** the test suite creates and drops the full schema per test, costing roughly three minutes on the Pi. Revisit with a session-scoped schema and per-test transaction rollback if the runtime starts discouraging test runs — that is the real cost, not the minutes.

---

## 8. Roadmap

**Season 12 (2025-26) is complete and fully ingested locally** — 17 rounds of real data. The entire scoring engine can be validated against a finished season before December. Biggest de-risking asset available.

### Phase 0 — Foundations, complete

| # | Step | Checkpoint |
|---|---|---|
| 0.1 | Local scaffold, app factory, config, `/health` | done |
| 0.2 | Local Postgres, `.env`, Alembic baseline | done — five tables |
| 0.3 | Auth blueprint plus deliberately unstyled templates | done — all flows by hand |
| 0.4 | pytest, `conftest.py`, auth tests | done |
| 0.5 | GitHub repo, first push | done |
| 0.6 | Railway project, Postgres, web service, env vars | done |
| 0.7 | Cloudflare CNAME plus Railway custom domain | done — session persists |
| 0.8 | Resend domain verification, live reset email | done |

**Phase 0 templates are semantic HTML with a ~30-line stylesheet, black on white.** No layout decisions, no colour, no components. They are replaced wholesale in Phase 3.

### Phase 1 — Data layer, complete

| # | Stage | Contents |
|---|---|---|
| 1.1 | Provider client | `providers/base.py` (normalised dataclasses, `ResultsProvider` protocol), `providers/ocblacktop.py` (UA validation, 403 classification, envelope normalisation, pagination, retry/backoff, the two-step season join) |
| 1.2 | Ingestion models | Season, Location, Meeting, Round, Session, Driver, Team, SeatEntry, Result, SyncConflict, plus migration `0002_ingestion_schema` |
| 1.3 | Season sync | Stage derivation, meeting derivation with admin override, round numbering, `Round.format` derivation, deadline computation, conflict classification per §6 |
| 1.4 | Results ingestion | Per-session ingest with status checks, season-scoped payload validation, S12 backfilled |

No worker service yet. There is nothing to poll until Season 13.

### Phase 2 — Scoring engine and simulation, complete

- **2a — engine.** `app/scoring/engine.py` and `lineups.py`, pure functions over
  result dicts. Validated against the five worked examples in §3.
- **2b — simulation.** `sim/`, run against all 17 backfilled S12 rounds.
  **Outcome: no point values changed.** Ruleset promoted to `v1`; the evidence
  is recorded in `app/scoring/rules.py` above `V1`.

**On the apparent Phase 1/2 ordering conflict:** Phase 2 must run before the *game* schema is fixed, not before all schema.

- **Ingestion schema** — fixed in Phase 1. The simulation cannot run without it.
- **Game schema** — LineupSnapshot, LineupPick, PickScore — stays unfixed until the simulation lands.

This works because `app/scoring/` imports nothing from Flask or SQLAlchemy: it takes plain result dicts and returns points, so `sim/` can exercise it without a web app. A test asserts this.

### Phase 3 — UI foundations
Design language, typeface selection (open licence), typographic scale, colour system as CSS custom properties, layout primitives. Lands before the lineup UI so nothing needs restyling later. Mockups before implementation.

### Phase 4 — Lineup & transfers
Staged-draft selection UI with client-side constraint validation and running transfer cost; server-side revalidation on commit; snapshot storage; transfer bank derivation; meeting deadline locking.

### Phase 5 — Scoring engine in production
Scoring worker with result completeness validation before scoring. Idempotent rescoring against a recorded ruleset version. Results polling with the rate limits in §6 respected.

### Phase 6 — Leagues & social
Multi-league membership, league creation and admin roles, invite links with caps, league tables, friend profiles. Scored once per user, projected into each league.

### Phase 7 — Visualisation
Points breakdown, dream team, qualifying bracket with personal highlighting, meeting views. **The main event — budget accordingly.**

Consider loading Season 12 into production for this phase: rehearsing the visualisations against 17 rounds of real results is a better test than synthetic data, and beats discovering at Jeddah that something falls apart on a phone.

### Milestones

| Date | Milestone |
|---|---|
| Aug 2026 | Phases 0–1 complete; S12 backfilled |
| Sept 2026 | Phase 2: scoring engine validated, simulation run, ruleset tuned |
| Oct 2026 | Phase 3: design language settled |
| Nov 2026 | Phases 4–6 |
| Early Dec 2026 | Phase 7; S13 calendar synced; friends registered; lineups locked in |
| **18–19 Dec 2026** | **Jeddah — first live round** |
| Late Dec 2026 | Re-tune places gained/lost against the first real Unleashed race |

Season 13: 21 races, 13 meetings. Gen4 debuts; Opel replaces DS; new venues at COTA, Zandvoort and Brands Hatch. Expect unpredictable early form.

---

## 9. The S12 simulation (Phase 2b)

The single highest-value task in the project, and the reason to do it before the game schema is fixed.

Write a standalone script in `sim/` — no Flask, no database beyond a read — that scores all 17 rounds of the backfilled S12 data. Then inspect:

1. **Is qualifying dominating the race?** Compare total quali vs race points distributed per round.
2. **What are the right magnitudes for places gained/lost?** It ships in v1, so this is a tuning question rather than a ship/don't-ship one. What share of variance does it account for at ±4? Does a ±2 cap, or a per-3-places step, produce a better distribution?
3. **Would a sensible lineup have beaten a random one?** Generate a few hundred random valid lineups, plus a "consensus best drivers" lineup, and compare. If random competes, the scoring isn't rewarding judgement.
4. **What does the score distribution look like** per round and cumulatively? Are there runaway leaders, or is it too tight to be interesting?
5. **How much would the transfer bank actually have mattered?** Simulate a never-transfers player against an optimal-transfers player. Include the two-transfer forced-relocation rule, since it constrains what the optimal player can do.
6. **Does the team slot pull its weight** at half-sum, or is it always the weakest of the five?
7. **How often does the dream team tie?** A high tie rate is a signal the gradient is too coarse.

**Caveat that must not be forgotten: S12 contains no sprint races.** Every S12 double-header ran two races of the same format. Season 13's Race 1 is a 30-minute high-downforce sprint with no Pit Boost, which will produce a different overtaking distribution and therefore different places-gained magnitudes. The simulation validates the *mechanic* and gives a defensible starting point; it cannot give correct magnitudes for Unleashed races. Plan an explicit re-tune after Jeddah, and rely on ruleset versioning so the re-tune doesn't rewrite history.

Outputs are point-value adjustments and a version-1 scoring ruleset. Budget a day.

### Outcome (19 Aug 2026)

Run against Season 12. No point values changed; ruleset promoted to `v1`.

- **Places gained/lost is load-bearing**, firing on 55.6% of driver-rounds,
  near-symmetrically. Cap 4 sits on the knee of the returns curve; a 3-place
  step scores better on spread but breaks merit ordering (P20 to P11 would
  outscore a podium).
- **The depth is entirely in transfer timing.** The best fixed lineup for the
  season and the obvious one are the same lineup, so there is no clever
  set-and-forget pick. Transfers are worth +100 over a season against a
  theoretical ceiling of +242.5.
- **The team slot is the low-variance pick.** Its mean equals the driver mean
  by construction (half the sum of two drivers is their average), but its
  spread is ~30% lower — sd 3.35 against 4.79. Picking a team is the
  conservative move; that is a feature, and worth making legible in the UI.
- Race took 61.4% of points distributed; season driver totals ran 104 down to 8.
- The dream team ties on 6 of 17 rounds, worst case 18 lineups out of 20,160.

Unchanged caveat: none of this is validated for E-Prix Unleashed. Re-tune after
Jeddah.

---

## 10. Open decisions

- **Late joiners:** a player starting at meeting 5 can never catch up on the season table. Options: a rolling "last 5 meetings" table alongside the season one, per-league season start dates, or accept it. `LeagueMembership.joined_at` already exists, so any of these stays available.
- **Places gained/lost cap and step:** ships at ±4 in steps of 5 places; confirm or adjust after the S12 simulation, then again after Jeddah.
- **Team score rounding:** halves permitted (decimal storage). Revisit only if league tables look untidy in practice.
- **Admin surface:** read-mostly by design — usage counts, sync health, last successful poll, provider quota, outstanding sync conflicts. Mutating actions are added per phase, must be idempotent, and are logged with actor and timestamp. Deadlines may be pushed later before they pass (consistent with the monotonic rule in §2); a passed deadline is never unlocked through the interface, because a lineup edited with results known cannot be made legible to the rest of the league. **Not yet built** — the conflicts view is the first thing it needs.
- **Meeting display name overrides:** `grouping_locked` currently guards both regrouping and renaming, so correcting "Monte Carlo" to "Monaco" also freezes the grouping. Worth splitting if it becomes annoying in practice.
- **Public/global table:** worth having alongside leagues if the app is shared online?
- **S13 qualifying points sanity check:** what the replacement expectation should be, once a real S13 payload exists.
- **S13 season UUID:** does not exist in `/seasons` yet. The sync resolves by ending year (2027) at run time; watch for it appearing.
- **Season 12 in production:** not loaded. Worth doing for Phase 7 so the visualisations get rehearsed against real results.

### Resolved

| Decision | Outcome |
|---|---|
| League structure | Invite-based, multi-league; built for medium scale; durable across seasons |
| Season-start grace | Unlimited free edits until the first deadline of the season |
| Long-term driver absence | Costs a normal transfer; no free move |
| Grid size | 20 drivers, 10 teams — verified, but never hard-coded |
| `participationRounds` | Nested per-team, an array of round numbers. Use it for the picker's rounds-participated; never as roster truth |
| Viewport | Mobile-first; desktop as a wide tablet, not a sprawling dashboard |
| Lineup visibility | Hidden until the meeting deadline, then visible to league co-members |
| Email | Password reset only; no reminders or notifications |
| Season scoping | `season_id` on all season-scoped tables from day one; leagues exempt |
| Transfer cost | Count of changed slots; forced team relocation costs 2, spent atomically |
| Lineup editing | Staged draft with explicit commit; server-side revalidation |
| Places gained/lost | **Ships in v1** — it is the only midfield resolver |
| **Fastest lap source** | **Minimum `lap_time`, never `fastestLap.rank`** — rank is eligibility-restricted and wrong on 8 of 17 S12 rounds |
| **Pole source** | Qual Final winner, never `gridPosition` — penalties move the grid, not the pole |
| Design ground | Light |
| Typography | Open licence only; chosen in Phase 3 |
| Design tokens | CSS custom properties, not Python config |
| Roster truth | Derived from API data; no curated entry list; rounds-participated shown in the picker |
| Deadline | Stored on Meeting with session provenance, monotonic once published |
| Sync conflicts | Safe changes apply silently; unsafe ones skip that meeting atomically and raise a flag |
| Ingested stages | Qualifying and race only; practice and `other` are never requested |
| Round numbering | Position in the season calendar; immutable once assigned |
| Round format gating | Unleashed rule applies from S13 only; S12 is uniformly `eprix` |
| Auth | Lifted from the F1 app with the divergences in §7 |
| Runtime | Python 3.11.2, Postgres 18.x both environments, psycopg 3 |
| Provider abstraction | Normalised dataclasses + protocol in `providers/base.py`; no vendor payload escapes the client |
| Scoring ruleset | **v1** — S12 simulation confirmed the provisional values unchanged |

---

## 11. Working practices

- **Plan first.** Decisions settled collaboratively before code; mockups before implementation on design-heavy work.
- **Phased, incremental delivery** with testable checkpoints. Resist scope creep.
- **Delivery method:** full-project tarballs for Phases 0–2 where the change is structural; targeted copy-paste snippets with precise file locations from Phase 3 onward, and for all fine-tuning, bug fixes and feature additions.
- **Commit style:** concise imperative, one or two sentences.
- **No emojis.** Country flags are fine.
- **Never migrate on race weekends.** S13 runs 18 Dec 2026 – 25 Jul 2027 across 13 meetings. Worker and scoring changes prefer the gaps; config and template changes are safe anytime.
- **Multi-line terminal work:** write to `/tmp` via `cat >` and run with `PYTHONPATH=. python /tmp/script.py` to avoid paste mangling.
- **Quote multi-word `.env` values.** python-dotenv tolerates `NAME=Formula E Fantasy`, but `source .env` reads it as a command invocation and fails obscurely.
- **Verify a hand-written migration by autogenerating twice.** Alembic silently omits `use_alter` foreign keys, so the first pass can look clean and be wrong. A second `flask db migrate` against the migrated database should report no changes.
- **Integer inputs:** `type="text"` with `inputmode="numeric"` rather than `type="number"` with `step="1"` — better mobile behaviour.
- This document lives at `docs/SPEC.md` and is the single source of truth. Re-upload to the Claude project whenever it changes materially.

---

## 12. Repo structure

```
fe-fantasy/
├── app/
│   ├── __init__.py          # application factory
│   ├── config.py            # environment and Flask only
│   ├── extensions.py
│   ├── cli.py               # set-admin, config-check, sync-season, backfill-results
│   ├── utils.py             # admin_required, client_ip, touch_last_seen
│   ├── auth/                # routes, forms, email, rate_limit
│   ├── admin/               # read-mostly; request-info diagnostic
│   ├── leagues/  invite/    # Phase 6
│   ├── lineups/             # Phase 4
│   ├── meetings/            # meeting and round views, Phase 7
│   ├── models/
│   │   ├── user.py
│   │   ├── league.py
│   │   ├── calendar.py      # Season, Location, Meeting, Round, Session
│   │   ├── grid.py          # Driver, Team, SeatEntry
│   │   └── result.py        # Result, SyncConflict
│   ├── providers/
│   │   ├── base.py          # normalised dataclasses + ResultsProvider protocol
│   │   ├── ocblacktop.py    # the only module that sees a vendor payload
│   │   └── errors.py        # Blocked / Auth / Request / Transient / Payload
│   ├── ingest/
│   │   ├── stages.py        # session name -> bracket stage
│   │   ├── derive.py        # meetings, round numbers, formats, deadlines
│   │   ├── conflicts.py     # fingerprinting and dedupe
│   │   ├── season.py        # the sync orchestrator
│   │   ├── results.py       # per-session result ingest
│   │   └── checks.py        # championship points sanity check
│   ├── scoring/             # rules.py, engine.py — no Flask, no SQLAlchemy
│   ├── templates/
│   └── static/css/          # base.css now; tokens.css and the system in Phase 3
├── worker/
│   └── scheduler.py         # Phase 5
├── sim/                     # Phase 2b standalone simulation
├── migrations/
├── tests/
│   └── fixtures/            # committed probe JSON
├── docs/SPEC.md
├── wsgi.py
├── requirements.txt
├── requirements-dev.txt
├── railway.toml
├── Procfile
├── .python-version
├── .env.example
└── README.md
```

Three deliberate choices:

- **`providers/` exists from the first commit**, per the §6 mitigation. A vendor swap becomes a new module implementing `ResultsProvider`, rather than a refactor of everything that touches results.
- **`scoring/` imports nothing from Flask or SQLAlchemy.** It takes plain result dicts and returns points. This resolves the Phase 1/2 ordering question and lets the simulation run without a database.
- **`sim/` sits outside `app/`** so there is no route by which the web application can be imported into it.

---

## Appendix A — API field reference

Observed 14 August 2026, corrected and extended 18–19 August 2026 against a full Season 12 ingest. Raw payloads are in `tests/fixtures/`.

### Session identification — read this before writing any parser

`session.type` has four values: `practice`, `qualifying`, `race`, `other`. **All nine qualifying sessions share `type: "qualifying"`**, so type alone cannot distinguish a group stage from a final. The bracket structure must be derived from `session.name`.

Observed names for one round, in schedule order:

```
practice    Free Practice 3
qualifying  Qual Group A
qualifying  Qual Group B
qualifying  Qual Quarter-Final 1
qualifying  Qual Quarter-Final 2
qualifying  Qual Quarter-Final 3
qualifying  Qual Quarter-Final 4
qualifying  Qual Semi-Final 1
qualifying  Qual Semi-Final 2
qualifying  Qual Final
race        Race
```

Treat these strings as **unstable**. Match defensively (normalised, case-insensitive substring), and **fail loudly on an unrecognised qualifying session name** rather than skipping it silently — a silent skip would corrupt scoring without any visible error. Sessions of any other type are recorded as `other` and ignored; Season 12 round 3 carries a "Rookie Free Practice" typed `other`, and Season 13's shakedown will most likely arrive the same way.

**Duel sessions return only their two participants.** A full bracket therefore requires all nine qualifying sessions to be fetched per round.

### Seasons index — `/seasons`

| Field | Notes |
|---|---|
| `id` | UUID. Required by `/seasons/{id}`; a numeric year returns 400. |
| `year` | **The year the season ENDS.** S12 (Dec 2025 – Aug 2026) is `2026`; S13 (Dec 2026 – Jul 2027) will be `2027`. |
| `status` | Null for every season observed. Not usable. |
| `roundCount` | Null for every season observed. Not usable. |

Twelve seasons present, 2026 back to 2015. **No 2027 entry as of 19 August 2026.**

### Season detail — `/seasons/{uuid}`

Bare object with four keys: `season`, `drivers` (20), `teams` (10), `schedule` (17).

`schedule[]` entries are events **without `schedule[]` of their own** — no session times. Driver entries carry standings (`position`, `points`) plus `teams[]`, each with `participationRounds`.

### Event object

| Field | Notes |
|---|---|
| `id` | UUID |
| `name` | Sponsor-polluted. Do not parse or group on it. |
| `dateStart` / `dateEnd` | Equal for Formula E — each event is a single day. Plain dates (`"2025-12-06"`), no time component. |
| `status` | `completed` \| `scheduled` |
| `location` | `{id, name, city, country{name, twoCode, threeCode}}` — `location.id` is stable across seasons |
| `schedule[]` | Embedded session array; only present via `/events`, not `/seasons/{uuid}` |

### Session object (inside `event.schedule[]`)

| Field | Notes |
|---|---|
| `id` | UUID, needed for the results path |
| `name` | The only way to identify a bracket stage |
| `type` | `practice` \| `qualifying` \| `race` \| `other` |
| `startTime` / `endTime` | **Note the naming — not `dateStart`/`dateEnd` as on the event.** ISO 8601 UTC with millisecond precision (`2026-07-26T06:40:00.000Z`) |
| `status` | `scheduled` \| `ongoing` \| `completed`. Check before requesting results. |

### Result row

| Field | Notes |
|---|---|
| `id` | UUID of the **result row**, not the driver |
| `position` | **String** (`"1"`) |
| `gridPosition` | **Int** (`5`). **The post-penalty starting slot, not the qualifying result** — Wehrlein took pole at São Paulo and started P4. Correct for places gained/lost; wrong for identifying pole. Present-and-null in qualifying sessions. Null or zero in a race means no places gained/lost score — log it. |
| `driver` | `{id, firstName, lastName, code, number}` — `code` null for 16 of 20; `id` is the only stable key |
| `team` | `{id, name, shortName, color}` — `color` unreliable |
| `carNumber` | Top-level, alongside `driver.number` |
| `status` | **Absent on qualifying rows.** Null for classified finishers, `"DNF"` for retirements. Retirements still receive ranked positions. |
| `points` | **Absent on qualifying rows.** String decimal (`"25.0"`) elsewhere — real FE championship points, season-dependent, see below. |
| `fastestLap` | `{rank, time, lap}` — **`rank: 1` marks the fastest lap among top-ten finishers, not of the race.** Disagrees with the quickest `lapTime` on 8 of 17 S12 rounds. Store it; the fantasy point comes from `lapTime` (§3). |
| `lapTime` / `displayTime` | **Semantics differ by session type.** In a race, `lapTime` is the driver's fastest lap and `displayTime` the total race time. In a qualifying duel, `lapTime` is null and `displayTime` carries the lap time (`"1:12.341"`). **`displayTime` shape varies:** `"1:01:13.217"` over an hour, `"59:23.013"` under. Branch on session type; never split on `:` expecting a fixed part count. |

**Always null in Formula E payloads** (populated for other series, so don't be misled by the schema): `laps`, `chassis`, `engineManufacturer`, `gap`, `interval`, `pitStops`, `bestLapTime`, `bestLapNumber`, `sectors`, `tireStrategy`, `q1Time`, `q2Time`, `q3Time`.

The absence of `laps` is why **retirement ordering is unavailable** — there is no way to know who retired first.

### Error shapes

`/seasons/2026` (numeric where a UUID is expected):

```json
{"message": "Validation failed (uuid is expected)", "error": "Bad Request", "statusCode": 400}
```

A Cloudflare 1010 block returns an **HTML** body with HTTP 403, distinguishing it from an API credential rejection, which returns JSON. Sustained request rates return **HTTP 429** — see the rate limiting note in §6.

### Real FE championship points (cross-validation, season-scoped)

**Season 12 and earlier:** `25 / 18 / 15 / 12 / 10 / 8 / 6 / 4 / 2 / 1` for the top ten, plus 3 for pole and 1 for fastest lap (top-ten finishers only). Useful as an ingest sanity check: if summed `points` don't match this distribution, the payload is incomplete.

The pole bonus attaches to the **Qual Final winner**, not to whoever starts P1, and it is paid even to a driver who retires — Mortara scored 3.0 from a P18 DNF at Tokyo.

**Season 13 onward:** the race distribution is unchanged, but qualifying now awards championship points on a sliding scale to the eight drivers reaching the Duels, worth roughly 105 points across the season. **The S12 check will produce false failures on S13 data.** The implementation is gated on season; write a replacement expectation once a real S13 payload is in hand.

The top ten still defines the "points finish" rule in §3, which is unaffected.

### Fixture inventory

| File | Contains |
|---|---|
| `events_bare.json` | 20 events with `meta` pagination block; mixed completed/scheduled; all carry `schedule[]` |
| `events_limit.json` | 50 events — demonstrates `?limit=` working |
| `events_page2.json` | Page 2 — for the client's page-walk test |
| `events_param_season.json` | `?season=` — byte-identical to `events_bare.json`, proving the parameter is ignored |
| `events_param_seasonid.json` | `?seasonId=` — same |
| `events_param_perpage.json` | `?perPage=` — same |
| `seasons_list.json` | 12 seasons, year → UUID; no 2027 |
| `season_detail.json` | S12, re-fetched after the London finale: calendar (17), driver standings (20), team standings (10) |
| `season_numeric_400.json` | The 400 "uuid is expected" error shape |
| `results_race.json` | Tokyo R2 race — 20 rows, 4 DNFs, `fastestLap.rank: 1` on one row, 16 null `driver.code`, over-hour `displayTime` |
| `results_qual_final.json` | 2 rows — duel session shape; `points` and `status` keys absent, `gridPosition` present-and-null |
| `results_saopaulo.json` | Season opener — 7 DNFs occupying P14–P20; sub-hour `displayTime` |

### Probe helper

```bash
fe() {
  local path="$1" out="$2" dir="$HOME/projects/fe-fantasy/scratch"
  local code
  code=$(curl -s -H "x-api-key: $OCB_API_KEY" \
    -A 'KitsniffFEFantasy/0.1.0 (+https://fe.kitsniff.com)' \
    "https://api.ocblacktop.com/v1/formula-e$path" \
    -o "$dir/$out.json" -w '%{http_code}')
  echo "$out.json  HTTP $code  $(wc -c < "$dir/$out.json") bytes"
}
```
