# Formula E Fantasy — Project Spec

**Status:** Phase 0 complete and deployed. Phase 1 stage 1 (provider client) complete.
**Last updated:** 18 August 2026
**Target:** Live before the Season 13 opener — Jeddah, 18–19 December 2026
**Domain:** `fe.kitsniff.com`

> **Revision note 1 (18 Aug 2026).** Implementation-planning session. Places gained/lost ships in v1 (§3); forced team relocation costs two transfers, spent atomically (§2); Season 13 sporting format changes recorded (§3, §6, Appendix A); `Round.format` added (§5); design ground fixed as light with open-licence typography (§1); config split and CSS-native design tokens (§7); auth-lift divergences recorded (§7); repo structure added (§12); Phase 0 broken down with checkpoints (§8).

> **Revision note 2 (18 Aug 2026).** Phase 0 shipped; Phase 1 stage 1 built. **The API differs from the original probe write-up in nine material ways — see §6 and Appendix A.** Two of them (`session.type` having four values, and qualifying rows omitting `points`/`status` rather than nulling them) would have crashed a parser written to the old spec. Also: sync conflict policy defined (§6); production proxy and session findings recorded (§7); Postgres version claim corrected (§7); fixture inventory expanded (Appendix A).

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

**Store the computed deadline on the Meeting; do not derive it at request time.** Formula E schedules move. The deadline is computed at season sync, then persisted.

**The deadline is monotonic once published: a resync may move it later, never earlier.** Without this rule a schedule shift retroactively locks players out of a meeting they were still editing, with no way to explain what happened. An earlier session time found at resync is a sync conflict (§6): the meeting is left untouched and flagged.

### Season-start grace

Unlimited free lineup edits until the **first deadline of the season** (Jeddah, 18 December 2026). Transfer accounting begins from meeting 2. A player who joins later gets the same unlimited-edit grace up to their first locked deadline.

### Absent drivers

A picked driver who does not appear in a session's results scores 0 for it. No substitution, no compensation.

If a driver leaves the grid mid-season (injury, contract change), the player must spend a normal transfer to replace them. **No free transfers**, deliberately: it avoids a special case, and it removes any route where a convenient absence hands someone an extra move.

**The roster is fully derived from API data.** No curated entry list, no admin-maintained "main driver" flag. One-off reserve drivers become pickable, and that is acceptable — the app must not assert who the regular drivers are, because it would eventually be wrong.

**Mitigation against misinforming users:** the driver picker shows rounds-participated alongside each driver. A reserve who has appeared once is then self-evidently a one-off without the app claiming anything. This figure comes directly from `driver.teams[].participationRounds` (§6) — it does not need computing from results.

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

**Fastest lap is unconditional here.** Formula E awards its championship fastest-lap point only to a driver finishing in the top ten; this game does not apply that condition. Derive it from `fastestLap.rank == 1` on the result row, never from the `points` field.

### Worked examples

| Scenario | Breakdown | Total |
|---|---|---|
| Pole, wins from P1, sets FL | Quali 8 + win 5 + podium 5 + points 2 + FL 1 + places 0 | **21** |
| Wins from P6, group exit | 5 + 5 + 2 + places gained 2 | **14** |
| Pole, retires (classified ~P18) | Quali 8 + places lost −4 | **4** |
| P4 quali, finishes P3 | Quali 3 + podium 5 + points 2 | **10** |
| P20 quali, finishes P11 | Places gained +2 | **2** |

### Places gained / lost — ships in v1

**Reversal of an earlier decision.** A previous draft of this spec deferred places gained/lost past v1 under a "ship with less" principle. That was wrong, for a specific reason: without it, race scoring has no midfield resolution at all.

Strip the rule out and the race gradient becomes P1 = 12, P2–P3 = 7, **P4–P10 = 2**, P11–P20 = 0. Seven consecutive finishing positions score identically. Most picks land in that band most weekends, the dream team ties constantly, and a P4 drive is indistinguishable from a P10 drive. Places gained/lost is the only rule that resolves the middle of the field, so it is not an optional extra — it is load-bearing.

Structurally asymmetric by design: a front-row qualifier has no upside and up to −4 exposure, a back-row qualifier has +4 upside and no risk. This is the main tension in lineup choice and partly counterbalances the value of strong qualifiers.

**DNFs punish themselves.** The API gives retirements ranked finishing positions (São Paulo's seven DNFs occupied P14–P20), so a retiring front-runner automatically takes the full −4. No separate DNF rule needed.

**Defensive handling.** If `gridPosition` is null or zero on a race result row (pit-lane start, data gap), score places gained/lost as 0 for that driver and log a warning. Never guess a grid slot.

**Magnitudes are provisional at ±4** and are the primary output of the S12 simulation (§9). See the caveat there about sprint races.

### Team scoring

**Half the sum of the team's two drivers' round scores**, including any negative places-lost values.

Keeps the team slot comparable in value to a driver slot, and creates a distinct judgement: you want a team whose *both* cars perform, which is a different call from picking one star.

Halves are permitted (drivers on 8 and 3 → team scores 5.5). Store as decimal; do not round, as rounding introduces a bias that needs explaining.

### Scoring rulesets are versioned and snapshotted

Point values are not constants in code. They live in `app/scoring/rules.py` as a named, versioned ruleset, and the ruleset in force is recorded against each Round when the round is created.

This is lifted from the F1 app's `round_scoring_config` pattern, and this project needs it more: §9 exists specifically to tune point values against real data, and the ±4 cap is explicitly provisional. Changing a value must never retroactively rewrite a completed round's score. Combined with the stored per-pick breakdown (§5), every historical score stays reproducible and rescoring stays idempotent.

---

## 4. Views

- **Lineup** — pick and manage the five slots; staged draft with explicit commit; transfer state, bank, and the running cost of the current draft clearly shown; rounds-participated shown per driver in the picker
- **Meeting view** — points earned, split into clearly headed sections labelled by round format (`E-Prix Unleashed` / `E-Prix`), not "Race 1 / Race 2"
- **Points breakdown** — per pick, per race, showing exactly which rules fired. The core data-presentation challenge, and the main design opportunity.
- **Dream team** — the highest-scoring valid lineup for each round, brute-forced across the actual roster (~20,160 combinations at current grid size — instant, no optimisation needed). A star marks any user pick that made it.
- **League table** — season standings within a league
- **Friend profile** — another player's season: lineups and points by meeting
- **Results with personal highlighting** — the qualifying bracket and race classification with the user's own picks marked. Personal stakes make the visualisation compelling in a way a neutral bracket is not.

---

## 5. Domain model

Three levels. The API has no meeting concept — it treats each race as a top-level "event" — so Meeting is derived.

```
Meeting    e.g. London          13 per season   ← user-facing chronology, transfer/deadline unit
  Round    R16, R17             21 per season   ← FE numbering, scoring unit
    Session  groups/duels/race  ~11 per round   ← ingestion only
```

**Naming:** `Meeting` internally, "Weekend" in the UI. **Do not use "event"** in the domain model — the API already uses it for a single race.

**Meeting derivation:** group by `location.id` + date adjacency within a season. **Never group by `name`** — sponsors are baked in ("2026 Hankook London E-Prix" vs "2025 Marvel Fantastic Four London E-Prix"). Store a clean display name ("London") separately.

Derive automatically at season sync with admin confirm/override. Thirteen meetings a season is a five-minute check that stops a calendar oddity breaking a race weekend.

`location.id` is stable across seasons, enabling multi-season location records.

### Round format — new for Season 13

`Round.format` with values `eprix` and `eprix_unleashed`.

Derived at sync by rule: a single-header meeting's only round is `eprix`; in a double-header, round 1 is `eprix_unleashed` and round 2 is `eprix`. **Admin-overridable, same pattern as meeting derivation** — the regulations say double-headers "typically" carry one of each, and typically is not always.

Used for UI labelling and, later, for any format-aware analysis (a 30-minute high-downforce sprint with no Pit Boost will not produce the same overtaking distribution as a 45-minute E-Prix).

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

### Verified quirks

Probed 14 August 2026; corrected and extended 18 August 2026 against a re-fetched corpus. **Where an earlier draft of this section said otherwise, this table is right.**

| Quirk | Detail |
|---|---|
| Three envelope styles | `/events` → `{data, meta}`; `/seasons/{id}` → bare object; `/results` → bare array. Normalised in the client layer. |
| Unknown params silently ignored | `?season=`, `?seasonId=`, `?perPage=` return **byte-identical** unfiltered responses with HTTP 200 — verified by hash. **Never treat a 200 as proof a filter applied.** Only `limit` and `page` work. |
| The events collection cannot be filtered | 165 events across all 12 seasons, with no server-side season filter. A season's session times require paging the whole collection and matching client-side against the event IDs from season detail. Four calls at `limit=50`. **Season sync is inherently a two-step operation.** |
| Pagination | `?limit=` and `?page=` work. `meta` = `{page, limit, total, totalPages}`. Default limit 20. |
| Seasons UUID-keyed | `/seasons/2026` → 400 "uuid is expected". `/seasons` gives the year → UUID index. |
| **Season `year` is the ENDING year** | S12 ran Dec 2025 – Aug 2026 and is keyed **2026**. S13 runs Dec 2026 – Jul 2027 and will be keyed **2027**. Reading it as the starting year silently returns the wrong season, because the payload is valid either way. |
| **Season 13 not yet published** | `/seasons` runs 2026 back to 2015 as of 18 Aug 2026. `status` and `roundCount` are null for every season, so year is the only usable selector. Resolve by year at run time and treat "not found" as a normal condition. |
| **`session.type` has four values** | `practice`, `qualifying`, `race`, **`other`**. The earlier claim of three was wrong. Season 13's shakedown day will most likely arrive as `other`. |
| **Sessions use `startTime`/`endTime`** | Events use `dateStart`/`dateEnd`. The two levels use opposite naming conventions; reading the event's names at session level yields a null deadline. |
| Sessions carry their own status | `scheduled` \| `ongoing` \| `completed`. The results poller should check this before requesting results rather than requesting and inferring from an empty array. |
| **Qualifying rows omit `points` and `status`** | Absent keys, not null ones — subscripting raises `KeyError` on nine of the eleven sessions in a round. `gridPosition` by contrast is present-and-null there. Read every field with `.get()`. |
| **`driver.code` is null for 16 of 20** | Not "frequently" — almost always. There is no code-based display path; **key on `driver.id` (UUID)**, label with `lastName` plus `number`, treat `code` as decoration. |
| Type inconsistency | `position` is a string (`"1"`), `gridPosition` an int (`5`), `points` a string decimal. Cast on ingest. |
| **`displayTime` has a variable shape** | `"1:01:13.217"` for a race over an hour, `"59:23.013"` for one under. Never split on `:` expecting three parts — the 30-minute E-Prix Unleashed will be sub-hour every time. |
| `team.color` unreliable | Andretti and Jaguar both `000000`; Nissan has a real value. Not a usable palette. |
| Season detail lacks sessions | `/seasons/{uuid}` gives calendar + standings but no session times. Those come only from `/events`. |

### Endpoint strategy

- **`/seasons`** — year → UUID index. Resolve the season by ending year.
- **`/seasons/{uuid}`** — full calendar plus driver and team standings in one 13.7KB call.
- **`/events?limit=50&page=N`** — session times and IDs (`schedule[]` embedded per event). Filter client-side.
- **`/events/{id}/sessions/{id}/results`** — per session.

**Quota:** ~11 sessions × 21 rounds ≈ 231 calls/season for full capture, plus 4–9 for the calendar join. Comfortably inside the free tier — but the results-polling worker is the real consumer. Bound polling to windows following a session's scheduled end, check session `status` first, back off, and stop on success.

### `participationRounds` — corrected

It lives **inside `driver.teams[]`**, not at driver level, and it is an **array of round numbers**, not a count:

```json
"teams": [{"id": "...", "name": "PORSCHE...", "participationRounds": [1, 2, ..., 17]}]
```

Two consequences. Being per-team, a mid-season driver switch is represented correctly — two entries with disjoint round arrays. And because it is exactly "rounds actually raced", **it is the source for the driver picker's rounds-participated figure**; the earlier instruction to compute this ourselves from results is unnecessary.

It remains a live counter that grows during a season: the 14 August probe showed 15 rounds against a 17-event schedule because London had not yet run; the re-fetch after the finale shows 17. **So it is still not roster truth** — a driver who has not yet raced has an empty array. Use it for display, never to decide who is on the grid.

### Sync conflict policy

A resync must be trustworthy enough to run unattended twice a day, and must never half-apply. So changes are classified, and **each meeting syncs in its own transaction**.

**Applied silently:** a new event appearing, a session time moving later, a name or status change, a result arriving.

**Skipped and flagged:** a deadline that would move earlier (the monotonic rule in §2), a meeting regrouping differently than it did previously, a round disappearing from the calendar, a session count that does not match the expected bracket shape.

An unsafe change rolls back that meeting untouched and records a `SyncConflict` row; the remaining meetings apply normally. The admin page lists outstanding conflicts; a clean run shows nothing. This gives blind trust in the sense that matters — nothing ever half-applies, and nothing surprising applies without saying so.

### Data quality

Cross-validation passed. At Tokyo R2, points matched finishing order; Dennis's 16 for P3 confirmed the +1 fastest lap bonus; Mortara's 3.0 from a P18 DNF matched his Qual Final win and `gridPosition: 1`. Qualifying and race payloads agree.

**Action:** spot-check driver–team pairings against a trusted source. Small vendors get lineups wrong; Cassidy at Citroën is worth an eyeball.

### Season 13 sporting changes — effect on ingest

Announced June 2026 for the Gen4 era. Three things matter here.

1. **Qualifying now awards championship points.** The top eight — those reaching the Duels — score on a sliding scale, up to roughly 105 points across the season's 21 qualifying sessions. **This breaks the Appendix A ingest sanity check**, which assumes qualifying contributes only a 3-point pole bonus to the race-row `points` field. Make the sanity check season-scoped: apply the S12 distribution only to seasons before S13, and write a separate S13 expectation once a real payload is available.
2. **Double-headers run two different race formats.** Race 1 is `E-Prix Unleashed` (30 minutes, high downforce, no Pit Boost, six-minute attack mode); race 2 is a standard `E-Prix` (45 minutes, with Pit Boost). See `Round.format` in §5.
3. **A shakedown day precedes each weekend.** Expect unfamiliar entries in `schedule[]`, most likely with `type: "other"`. The parser must fail loudly only on unrecognised *qualifying* session names (Appendix A); anything else is ignored with a log line.

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
| Season scoping | Put `season_id` on every season-scoped table from day one. Leagues are the exception — they are durable across seasons; scoping applies to standings computed over them. |

**Consequence of the no-email policy:** all engagement pressure sits in the interface. The deadline state, unused transfer count, and "your lineup is unchanged since last meeting" condition need to be prominent on first load — there is no external nudge. This is workable precisely because the fantasy model degrades gracefully: a forgotten meeting still scores, so a missed reminder is not a lost player.

### Deployment notes (learned in Phase 0)

- **Migrations run as a Railway pre-deploy command** (`flask db upgrade`), not from application startup. Startup migration races across gunicorn workers, and a failure there puts a container with the wrong schema in front of traffic. Pre-deploy runs once and aborts the deploy on failure.
- **Healthcheck path is `/health`**, set in `railway.toml` and in the service settings. Without it a deploy that boots but cannot reach Postgres reports "online".
- **Cloudflare SSL/TLS must be Full (strict).** Flexible sends plaintext to Railway, so `SESSION_COOKIE_SECURE` cookies never return and login silently fails to persist — which presents as an auth bug, not a TLS setting.
- **The Railway-generated `*.up.railway.app` domain is deleted** once the custom domain works. `CF-Connecting-IP` is only trustworthy for traffic that passed through Cloudflare, so leaving the direct route open lets anyone forge their own rate-limit key.
- **`DATABASE_PUBLIC_URL` requires enabling the TCP proxy** on the Postgres service; new Railway Postgres instances are private-only by default. `DATABASE_URL` (private) stays as the application's variable — no egress cost, lower latency.
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

---

## 8. Roadmap

**Season 12 (2025-26) is complete and fully available** — 17 rounds of real data. The entire scoring engine can be validated against a finished season before December. Biggest de-risking asset available.

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

### Phase 1 — Data layer

| # | Stage | Contents |
|---|---|---|
| 1.1 | Provider client — complete | `providers/base.py` (normalised dataclasses, `ResultsProvider` protocol), `providers/ocblacktop.py` (UA validation, 403 classification, envelope normalisation, pagination, retry/backoff, the two-step season join), 43 tests against committed fixtures with no network |
| 1.2 | Ingestion models | Season, Meeting, Round, Session, Driver, Team, SeatEntry, Result, SyncConflict, plus the migration |
| 1.3 | Season sync | Meeting derivation with admin override, `Round.format` derivation, deadline computation, conflict classification per §6 |
| 1.4 | Backfill | All 17 rounds of S12 ingested and queryable |

No worker service until 1.4 — there is nothing to poll before then.

### Phase 2 — Scoring simulation (standalone)
See §9.

**On the apparent Phase 1/2 ordering conflict:** Phase 2 must run before the *game* schema is fixed, not before all schema.

- **Ingestion schema** — Meeting, Round, Session, Driver, Team, Result — is fixed in Phase 1. The simulation cannot run without it.
- **Game schema** — LineupSnapshot, LineupPick, ScoringRuleset, PickScore — stays unfixed until the simulation lands.

This works because `app/scoring/` imports nothing from Flask or SQLAlchemy: it takes plain result dicts and returns points, so `sim/` can exercise it without a web app. A test asserts this.

### Phase 3 — UI foundations
Design language, typeface selection (open licence), typographic scale, colour system as CSS custom properties, layout primitives. Lands before the lineup UI so nothing needs restyling later. Mockups before implementation.

### Phase 4 — Lineup & transfers
Staged-draft selection UI with client-side constraint validation and running transfer cost; server-side revalidation on commit; snapshot storage; transfer bank derivation; meeting deadline locking.

### Phase 5 — Scoring engine
Production scoring worker with result completeness validation before scoring. Idempotent rescoring against a recorded ruleset version.

### Phase 6 — Leagues & social
Multi-league membership, league creation and admin roles, invite links with caps, league tables, friend profiles. Scored once per user, projected into each league.

### Phase 7 — Visualisation
Points breakdown, dream team, qualifying bracket with personal highlighting, meeting views. **The main event — budget accordingly.**

### Milestones

| Date | Milestone |
|---|---|
| Sept 2026 | Phase 1: S12 fully backfilled and queryable |
| Sept/Oct 2026 | Phase 2: scoring validated and tuned against S12 |
| Oct 2026 | Phase 3: design language settled |
| Nov 2026 | Phases 4–6 |
| Early Dec 2026 | Phase 7; S13 calendar synced; friends registered; lineups locked in |
| **18–19 Dec 2026** | **Jeddah — first live round** |
| Late Dec 2026 | Re-tune places gained/lost against the first real Unleashed race |

Season 13: 21 races, 13 meetings. Gen4 debuts; Opel replaces DS; new venues at COTA, Zandvoort and Brands Hatch. Expect unpredictable early form.

---

## 9. The S12 simulation (Phase 2)

The single highest-value task in the project, and the reason to do it before the game schema is fixed.

Write a standalone script in `sim/` — no Flask, no database — that reads the backfilled S12 data and scores all 17 rounds. Then inspect:

1. **Is qualifying dominating the race?** Compare total quali vs race points distributed per round.
2. **What are the right magnitudes for places gained/lost?** It ships in v1, so this is a tuning question rather than a ship/don't-ship one. What share of variance does it account for at ±4? Does a ±2 cap, or a per-3-places step, produce a better distribution?
3. **Would a sensible lineup have beaten a random one?** Generate a few hundred random valid lineups, plus a "consensus best drivers" lineup, and compare. If random competes, the scoring isn't rewarding judgement.
4. **What does the score distribution look like** per round and cumulatively? Are there runaway leaders, or is it too tight to be interesting?
5. **How much would the transfer bank actually have mattered?** Simulate a never-transfers player against an optimal-transfers player. Include the two-transfer forced-relocation rule, since it constrains what the optimal player can do.
6. **Does the team slot pull its weight** at half-sum, or is it always the weakest of the five?
7. **How often does the dream team tie?** A high tie rate is a signal the gradient is too coarse.

**Caveat that must not be forgotten: S12 contains no sprint races.** Every S12 double-header ran two races of the same format. Season 13's Race 1 is a 30-minute high-downforce sprint with no Pit Boost, which will produce a different overtaking distribution and therefore different places-gained magnitudes. The simulation validates the *mechanic* and gives a defensible starting point; it cannot give correct magnitudes for Unleashed races. Plan an explicit re-tune after Jeddah, and rely on ruleset versioning so the re-tune doesn't rewrite history.

Outputs are point-value adjustments and a version-1 scoring ruleset. Budget a day.

---

## 10. Open decisions

- **Late joiners:** a player starting at meeting 5 can never catch up on the season table. Options: a rolling "last 5 meetings" table alongside the season one, per-league season start dates, or accept it. `LeagueMembership.joined_at` already exists, so any of these stays available.
- **Places gained/lost cap and step:** ships at ±4 in steps of 5 places; confirm or adjust after the S12 simulation, then again after Jeddah.
- **Team score rounding:** halves permitted (decimal storage). Revisit only if league tables look untidy in practice.
- **Admin surface:** read-mostly by design — usage counts, sync health, last successful poll, provider quota, outstanding sync conflicts. Mutating actions are added per phase, must be idempotent, and are logged with actor and timestamp. Deadlines may be pushed later before they pass (consistent with the monotonic rule in §2); a passed deadline is never unlocked through the interface, because a lineup edited with results known cannot be made legible to the rest of the league.
- **Public/global table:** worth having alongside leagues if the app is shared online?
- **S13 qualifying points sanity check:** what the replacement expectation should be, once a real S13 payload exists.
- **S13 season UUID:** does not exist in `/seasons` yet. The sync resolves by ending year (2027) at run time; watch for it appearing.

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
| Design ground | Light |
| Typography | Open licence only; chosen in Phase 3 |
| Design tokens | CSS custom properties, not Python config |
| Roster truth | Derived from API data; no curated entry list; rounds-participated shown in the picker |
| Deadline | Stored on Meeting, monotonic once published |
| Sync conflicts | Safe changes apply silently; unsafe ones skip that meeting atomically and raise a flag |
| Auth | Lifted from the F1 app with the divergences in §7 |
| Runtime | Python 3.11.2, Postgres 18.x both environments, psycopg 3 |
| Provider abstraction | Normalised dataclasses + protocol in `providers/base.py`; no vendor payload escapes the client |

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
│   ├── cli.py               # set-admin, config-check
│   ├── utils.py             # admin_required, client_ip, touch_last_seen
│   ├── auth/                # routes, forms, email, rate_limit
│   ├── admin/               # read-mostly; request-info diagnostic
│   ├── leagues/  invite/    # Phase 6
│   ├── lineups/             # Phase 4
│   ├── meetings/            # meeting and round views, Phase 7
│   ├── models/
│   │   ├── user.py
│   │   ├── league.py
│   │   ├── calendar.py      # Season, Meeting, Round, Session   (1.2)
│   │   ├── grid.py          # Driver, Team, SeatEntry           (1.2)
│   │   ├── result.py        # Result, SyncConflict              (1.2)
│   │   ├── lineup.py        # LineupSnapshot, LineupPick        (Phase 4)
│   │   └── score.py         # ScoringRuleset, PickScore         (Phase 5)
│   ├── providers/
│   │   ├── base.py          # normalised dataclasses + ResultsProvider protocol
│   │   ├── ocblacktop.py    # the only module that sees a vendor payload
│   │   └── errors.py        # Blocked / Auth / Request / Transient / Payload
│   ├── ingest/              # sync_season, derive_meetings, sync_results  (1.3–1.4)
│   ├── scoring/             # rules.py, engine.py — no Flask, no SQLAlchemy
│   ├── templates/
│   └── static/css/          # base.css now; tokens.css and the system in Phase 3
├── worker/
│   └── scheduler.py         # from 1.4
├── sim/                     # Phase 2 standalone simulation
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

Observed 14 August 2026, corrected and extended 18 August 2026. Raw payloads are in `tests/fixtures/`.

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

Treat these strings as **unstable**. Match defensively (normalised, case-insensitive substring), and **fail loudly on an unrecognised qualifying session name** rather than skipping it silently — a silent skip would corrupt scoring without any visible error. Sessions of any other type may be ignored with a log line; Season 13's shakedown will most likely arrive as `other`.

**Duel sessions return only their two participants.** A full bracket therefore requires all nine qualifying sessions to be fetched per round.

### Seasons index — `/seasons`

| Field | Notes |
|---|---|
| `id` | UUID. Required by `/seasons/{id}`; a numeric year returns 400. |
| `year` | **The year the season ENDS.** S12 (Dec 2025 – Aug 2026) is `2026`; S13 (Dec 2026 – Jul 2027) will be `2027`. |
| `status` | Null for every season observed. Not usable. |
| `roundCount` | Null for every season observed. Not usable. |

Twelve seasons present, 2026 back to 2015. **No 2027 entry as of 18 August 2026.**

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
| `gridPosition` | **Int** (`5`). Present-and-null in qualifying sessions. Null or zero in a race means no places gained/lost score — log it. |
| `driver` | `{id, firstName, lastName, code, number}` — `code` null for 16 of 20; `id` is the only stable key |
| `team` | `{id, name, shortName, color}` — `color` unreliable |
| `carNumber` | Top-level, alongside `driver.number` |
| `status` | **Absent on qualifying rows.** Null for classified finishers, `"DNF"` for retirements. Retirements still receive ranked positions. |
| `points` | **Absent on qualifying rows.** String decimal (`"25.0"`) elsewhere — real FE championship points, season-dependent, see below. |
| `fastestLap` | `{rank, time, lap}` — `rank: 1` on the setter only; all null for everyone else. Use this for the fantasy FL point, not `points`. |
| `lapTime` / `displayTime` | **Semantics differ by session type.** In a race, `lapTime` is a lap time and `displayTime` the total race time. In a qualifying duel, `lapTime` is null and `displayTime` carries the lap time (`"1:12.341"`). **`displayTime` shape varies:** `"1:01:13.217"` over an hour, `"59:23.013"` under. Branch on session type; never split on `:` expecting a fixed part count. |

**Always null in Formula E payloads** (populated for other series, so don't be misled by the schema): `laps`, `chassis`, `engineManufacturer`, `gap`, `interval`, `pitStops`, `bestLapTime`, `bestLapNumber`, `sectors`, `tireStrategy`, `q1Time`, `q2Time`, `q3Time`.

The absence of `laps` is why **retirement ordering is unavailable** — there is no way to know who retired first.

### Error shapes

`/seasons/2026` (numeric where a UUID is expected):

```json
{"message": "Validation failed (uuid is expected)", "error": "Bad Request", "statusCode": 400}
```

A Cloudflare 1010 block returns an **HTML** body with HTTP 403, distinguishing it from an API credential rejection, which returns JSON.

### Real FE championship points (cross-validation, season-scoped)

**Season 12 and earlier:** `25 / 18 / 15 / 12 / 10 / 8 / 6 / 4 / 2 / 1` for the top ten, plus 3 for pole and 1 for fastest lap (top-ten finishers only). Useful as an ingest sanity check: if summed `points` don't match this distribution, the payload is incomplete.

**Season 13 onward:** the race distribution is unchanged, but qualifying now awards championship points on a sliding scale to the eight drivers reaching the Duels, worth roughly 105 points across the season. **The S12 check will produce false failures on S13 data.** Gate it on season and write a replacement expectation once a real S13 payload is in hand.

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
