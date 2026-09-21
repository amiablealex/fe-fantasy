# FE Fantasy — Project Spec

**Status:** Phases 0–8 complete. Season 12 backfilled and scored locally; the worker runs in production as a five-minute cron job and is idling until the Season 13 calendar is published.
**Last updated:** 21 September 2026
**Target:** Live before the Season 13 opener — Jeddah, 18–19 December 2026
**Domain:** `fe.kitsniff.com`

> **Revision note 1 (18 Aug 2026).** Implementation-planning session. Places gained/lost ships in v1 (§3); forced team relocation costs two transfers, spent atomically (§2); Season 13 sporting format changes recorded (§3, §6, Appendix A); `Round.format` added (§5); design ground fixed as light with open-licence typography (§1); config split and CSS-native design tokens (§7); auth-lift divergences recorded (§7); repo structure added (§12); Phase 0 broken down with checkpoints (§8).

> **Revision note 2 (18 Aug 2026).** Phase 0 shipped; Phase 1 stage 1 built. The API differs from the original probe write-up in nine material ways — see §6 and Appendix A. Two of them (`session.type` having four values, and qualifying rows omitting `points`/`status` rather than nulling them) would have crashed a parser written to the old spec. Also: sync conflict policy defined (§6); production proxy and session findings recorded (§7); Postgres version claim corrected (§7); fixture inventory expanded (Appendix A).

> **Revision note 3 (19 Aug 2026).** Phase 1 complete: provider client, ingestion schema, season sync and results backfill. Season 12 is fully ingested locally — 11 meetings, 17 rounds, 187 sessions, 880 result rows. **§3's fastest-lap rule is corrected: derive it from the minimum `lap_time`, not from `fastestLap.rank`, which encodes Formula E's top-ten restriction and disagrees on eight of seventeen S12 rounds.** Also: `gridPosition` is the post-penalty starting slot, not the qualifying result (Appendix A); the provider rate-limits at roughly two requests per second (§6); practice and `other` sessions are never ingested (§6); Phase 2 splits into engine then simulation (§8, §9).

> **Revision note 6 (20 August 2026).** Phase 3 complete. The design language is settled and recorded in §1: Archivo and Anybody, a seven-step rem scale, CSS-native tokens in two tiers under cascade layers, and a two-stripe hue-seeded team palette. §4.1 records the lineup component as an architectural commitment; §4.2 records the driver and team profile. HTMX is in use (§7). The qualifying bracket is deferred to Phase 7, where the roadmap already places it; the interim is a linear stage list, and the open risk is recorded in §8.

> **Revision note 7 (21 August 2026).** Phase 4 complete. The game schema is fixed and recorded in §5: sparse snapshots per (user, meeting), picks as rows, the slot diff stored on the snapshot. §2 gains three rules the earlier drafts left open — only the earliest unlocked weekend is editable, the cost baseline is the last snapshot from an *earlier* meeting, and a late joiner's bank starts at one. §4 finally carries the subsections revision note 6 promised: §4.1 the lineup component, §4.2 the profiles, §4.3 the editor. `app/lineups/` exists (§12) and the roster and draft helpers have moved into it out of the debug-only styleguide package. The auth pages and the app shell now use the design system, and `base.css` is deleted.

> **Revision note 8 (22 August 2026).** Phase 5 complete. Scores are stored and read rather than recomputed (§5), scoring is partial and provisional by design (§3), the live poller inverts §6's status-check rule for a specific and measured reason (§6), and the worker runs on Railway (§7). Three things diverge from what earlier drafts of this document said: §5 asked for one table and got two; §6 said check status before fetching and the live path does not; and `railway.toml` is deleted, because Railway deprecated Config as Code with a cutoff seventeen days before Jeddah. A defect is recorded in §3 — the bridge scored every round against the *current* ruleset rather than the round's own, which would have rewritten history at the first re-tune.

> **Revision note 9 (22 August 2026).** Phase 6 complete. Leagues, invites, standings and friend profiles. Three things settled here go beyond what earlier drafts said. §2's visibility rule is split into the two predicates it always was, and the co-membership half is relaxed by *data* — a global league holding every user — rather than by deleting a predicate; §10 had already left "public/global table" open, so this closes it. §10's late-joiner question is answered mostly by §2's own rule that membership is a view over scores: joining a league late costs nothing, and what remains is a new *account* mid-season, which a shared range control addresses honestly and a per-member start date would not. And two defects are recorded in §11, both found by using the app rather than by a test: a form helper named into a WTForms hook, and an editor that asked a transfer diff a question about saving.

> **Revision note 10 (23 August 2026).** Phase 7 complete — the visualisation phase, and the last one before Jeddah. Six things here go beyond, or against, what earlier drafts said.
>
> **The Perfect Five is no longer the best *valid* lineup.** §4 and §10 both said "the highest-scoring valid lineup", and that produced a page a reader could not parse: a driver who outscored three of the five was absent because a higher-scoring team-mate held his team's slot. It is now the four best-scoring drivers and the best-scoring team, which is what the name means, needs no explanation, and cannot tie. The benchmark is given up deliberately (§4.5).
>
> **One unit, and it is fantasy points.** Formula E's own championship points are ingested for §6's payload check and are rendered nowhere. The classification's last column is FP, and the profile's `TP` is `FP` (§4.2, §4.6).
>
> **The qualifying bracket closed Phase 3's open risk by demonstration.** It needed no new token and no new primitive (§4.7).
>
> **`scoring_bridge` split into four modules, not the three §8 named** (§12), and the shim that carried the phase across its callers is deleted with a test asserting it stays deleted.
>
> **Every scored view is one shape** — nav bar, verdict, lineup — with the verdict's label the only variable (§4.4). Arrows where a reader can move; the same bar without them where they cannot.
>
> **No migration.** Season history, the bracket, the Perfect Five and the whole meeting view are reads over rows the scoring pass already wrote. The last migration in this project is `0006`.
>
> §11 gains five entries, one of which — separating "what did this cost" from "is there anything to save" — is the same mistake found in four places.

> **Revision note 11 (25 August 2026).** Phase 8 complete — visual refinement, taken in a gap the roadmap opened rather than planned. Seven things here go beyond, or against, what earlier drafts said.
>
> **§8 is reordered.** Phase 8 was production readiness and could not start: every one of its entry conditions is gated on a Season 13 calendar the provider has not published. Visual work needs no calendar, so it took the gap. Production readiness is Phase 9, unchanged apart from its number, and November is still clear.
>
> **§1 gains a surface, and this is the substantive change.** "Typography and layout do the work colour would otherwise do" stands, but it had been read as *no fills anywhere*, and the consequence was an application with one word for a boundary: a line. A rule says two things are adjacent and different. It never says six things are one thing, and at the density Phase 7 reached, a reader was being asked to infer every group from its edges. `.slot` had already found this alone in Phase 4 and its own comment said so — a recessed ground was "most of the newspaper problem, not a lack of decoration" — and it was never generalised past the one component. Phase 8 generalised it. See §1's surface rule.
>
> **The mark family gains a rule** — a circle is an action, a square is a state — along with a wordmark and a favicon. The favicon is the only asset in this project and exists because a phone home screen cannot be set in type.
>
> **Motion exists**, at four applications and no fifth.
>
> **Navigation is two rows, and the footer carries the growth.** A live figure under each tab was drafted and dropped: two were clutter above pages already full of numbers, and the third could not be written at all, because a player in four leagues has four positions and a header has no room to say which one it means.
>
> **`/leagues/<id>` is two pages.** The split removed a duplication rather than hiding one — the membership list was the standings table's own people in a different order.
>
> **The static pages exist** (§4.9), and registration being public makes privacy and terms a requirement rather than a courtesy. `/how-to-play` renders every figure from `app/scoring/rules.py`, because a typed one would start lying the day the post-Jeddah re-tune ships.
>
> §11 gains six defects. Three are mine, one is a class of instruction rather than a bug, and every one of them failed silently rather than loudly.

> **Revision note 12 (21 September 2026).** An efficiency pass on the Railway deployment, taken in Phase 9's waiting period. August's bill was $3.29 and almost all of it was resident memory — CPU cost under a cent — for three processes held in RAM around the clock by a game that is idle most of the year. Nothing about the game changed.
>
> **The web service is one gunicorn process with four threads, and sleeps.** Two sync workers were two full copies of the application serving a friend group. Serverless puts the service to sleep after ten minutes without outbound traffic, and the first request after a sleep pays a cold start. Deadlines are unaffected: a lock is a comparison against `clock.now()` at request time (§2), not a job anything has to run.
>
> **The worker is a Railway cron job** — `python -m worker.tick` every five minutes, doing whatever is due and exiting. APScheduler is gone, and so is the one-replica rule: Railway skips a scheduled run while the previous one is active, so the platform now enforces what was a dashboard setting nobody could check from inside the process. Results land up to five minutes later than before, accepted in exchange (§7).
>
> **The worker keeps no state between runs**, and two things relied on it. The poll's patient phase no longer remembers when a session was last tried; it attempts on the first tick after each fifteen-minute boundary, which is arithmetic over the stored schedule and is pinned by a test against every cron phase (§6). The hourly heartbeat reads `WorkerRun` rather than a process global, which closes §10's restart-visibility item by removing restarts.
>
> Postgres stays always-on and is expected to be most of the remaining bill: the worker touches it every five minutes, and a database that sleeps behind a race-weekend poller is not a saving worth having. No migration.

---

## 1. Concept

A fantasy team game for the ABB FIA Formula E World Championship, built for a small friend group. Each player picks **4 drivers + 1 team**. Those five picks earn points from real race weekend performance. One transfer per meeting, bankable up to two.

Companion to the existing F1 Predictions app (`f1.kitsniff.com`) but a separate, standalone application.

### Why fantasy rather than predictions

- **Graceful degradation.** Season 13 runs 18 December – 25 July: eight months, 13 meetings. A player who forgets the app for a month still scores. A predictions app returns zeros and loses them permanently. For a casual group over a long season, this single property outweighs everything else.
- **Inherently social.** League tables and comparing lineups are the point, not a bolt-on.
- **Clearer scope.** Fantasy games have a known shape and a definition of done.
- **Richer data to present.** Five picks × ~7 scoring routes × 21 races × 13 meetings, plus transfer history and Perfect Five comparison — a far better canvas than five booleans per round.

### Design values

The real goal of this project is learning UI, UX, and the clear, beautiful presentation of dense structured data.

- Minimal, clean, engaging — but clarity beats minimalism when data is dense
- Genuinely unique; must not read as generically generated
- **Avoid "AI-flag" patterns:** hero graphics, pill-shaped tags, gradient shading, decorative iconography
- Typography and layout do the work that colour and decoration would otherwise do
- No reuse of the F1 app's parchment/moss language — clean-sheet visual exercise
- This explicitly retires the pill component used throughout the F1 app

**Ground: light.** Deliberately contrary to Formula E's own very dark brand identity, and contrary to the default look of a motorsport data app. A light ground also makes the negative values in places-lost scoring easier to render legibly without resorting to alarm-red fills.

**Typography: open licence only.** No paid font licences. Archivo (OFL, variable, wght 100–900 / wdth 62–125) for all text and data. Anybody (OFL, variable) for display only, at width 100 and weight 700. Anybody's scope is round numbers, meeting mastheads, and pick or lineup totals — nothing else, never below 20px, never in a table cell. Both self-hosted and subset to Latin Extended; no font CDN.

**Design tokens live in CSS, not Python.** Colour, spacing, and type scale belong in `static/css/tokens.css` as custom properties. The F1 app's approach — a `PALETTE` dict in `config.py` injected into Jinja — makes every colour tweak a Python edit and a redeploy, and blocks `color-mix()`, `light-dark()`, and relative colour syntax. Do not repeat it.

**Scale in rem**, data size 13px equivalent. Form inputs are pinned at 16px, because iOS Safari zooms the viewport on a smaller focused input.

**Two non-team chromas, and only two.** There is no accent colour in v1: ten team hues already occupy the colour space, and an eleventh for personal marking would either lose to them or shout over them. Personal marking is structural — full ink, heavier weight, and a rule in a reserved gutter, a treatment nothing else on the page has, which survives being screenshotted, printed, or read by someone colour-blind.

The two exceptions are both states rather than identities, and both sit **outside the team clamp** so neither can be mistaken for a team:

| Token | State | Why it is outside the clamp |
|---|---|---|
| `--error` | A rule is broken; this cannot be saved as it stands | Three teams on this grid are red, so it is darker and more saturated than any stripe can be |
| `--caution` | Nothing is wrong; something is waiting to be saved | Yellows are why `--team-l-bright` exists at all — a yellow seed cannot hold chroma at `--team-l` — so this sits at L 0.47, far below that ceiling |

Added in Phase 7, when the editor needed to distinguish "you have unsaved changes" from "your lineup is invalid". They are genuinely different facts and colour says so faster than wording does; sharing red between them would have emptied red of meaning, which is the same argument §4.1 makes about never marking a transferred-in pick in the error colour.

**Team colour is two stripes**, seeded from `team.color` for hue only; lightness and chroma come from `tokens.css` and are routed by hue to one of two clamp tiers, because yellows and cyans cannot hold chroma at the lightness reds and purples can. The secondary stripe carries a second, independent channel: solid, tint, dark, or light. Seeds and overrides live in `app/palette.py` — data repair, not design. An unseeded team degrades to a neutral rule.

### Surfaces — the rule added in Phase 8

**A surface is warranted when a region must be read as a unit and then left.** Never for emphasis, never for importance, never for state.

Three grounds, and the phase that introduced the middle one added no fourth on purpose:

| Tier | Value | Job |
|---|---|---|
| Ground | `--surface` | the page. Everything sits here unless it has earned otherwise |
| Recessed | `--surface-recessed` | a region read as a unit: a panel, a bracket section, a lineup slot, a form control |
| Inked | `--ink-900` | the verdict block. One per screen, carrying the single figure the screen exists to give |

Four constraints, which matter more than the token:

1. **A fill replaces a rule; it never joins one.** Every heavy rule that became a panel is a line removed, which is why the page got quieter rather than busier. `--rule-heavy` appeared seven times before Phase 8, five of them in full ink, so a weekend page carried four to six 3px black rules at 360px. It now appears once, on the appbar, at the boundary between the app's chrome and its content.
2. **No recessed surface nests inside another.** Where the case genuinely arises the inner one inverts to paper — a form control inside a panel, and a bracket stage inside a bracket section.
3. **A surface holds a heading and a list.** Never a single statement, never a lone figure: fill something small enough and you have rebuilt the pill this project retired.
4. **A surface is full-measure and square.** It never sits on a grid beside a sibling and never takes a corner radius. There is no `--radius` token and that is deliberate.

**The band bleeds through the page's inline padding**, so on a phone it runs the full width of the screen. A band with no left or right edge cannot be read as a tile on a grid, which is what keeps this out of the card look above.

**A panel may be a disclosure.** `<details class="panel">` is how the bracket became four summaries and how a fifty-member list stops being the longest thing on a page.

### The mark family

A glyph from the display face inside a geometric container. No icon asset enters the project.

**A circle is an action — press it and something opens. A square is a state — it is telling you a fact and cannot be pressed.** That describes both marks that already existed, and it is the test any new one has to pass.

Two sizes only, `currentColor` throughout. Members: `!` in a square for the two problem levels, `i` in a circle for a profile, an initial in a circle for the account.

**The star is the one exemption**, and it is documented rather than left as an inconsistency: every other mark occupies a slot of its own, where the star sits inside running text beside a driver's name, and a container would outweigh the word it marks.

**A cog was considered and refused.** A cog is not a character but an asset, so it would replace the family's rule with "circles containing whatever suits", and the second icon then costs nothing to justify. It would also have under-described its destination, which is members and an invite code as much as it is settings.

### Motion

**Motion confirms a change the reader caused.** Never on load, never looping, never announcing.

Two tokens and four applications, and there is not a fifth: a sheet arriving, a disclosure opening, a results fragment settling, and a tab becoming current. Exit is instant everywhere — a dismissal should feel finished the moment it is asked for.

The `prefers-reduced-motion` block is the one deliberately unlayered rule in the project, because it has to beat every layer to do its job.

### Identity

**The wordmark is the type system in miniature**: "FE" in Anybody at display weight, "Fantasy" in Archivo condensed tracked caps. The same relationship every screen uses — the display face for what behaves like a figure, the text face for what behaves like a label. It needs no drawing and degrades to the words.

The two stripes precede it, in ink rather than a team hue, because ten hues are already on the grid and an eleventh at the top of every page would be read as an identity.

**One asset exists: `favicon.svg`.** F and E are rectilinear letters, so they are drawn as rectangles rather than outlined from a font — the mark needs no font file, renders identically at 16px, and cannot break if the Anybody subset is regenerated. Paper ground, per the light-ground argument above: every other motorsport app on a home screen is dark.

### Navigation

**Two rows, and the split is what stops it growing.** Row one is the wordmark and the account control; row two is the three destinations a player moves between. Everything else — how to play, about, privacy, terms, admin — is in the footer, because those are visited rarely and deliberately.

No hamburger and no bottom tab bar: one reads as a menu of things that would not fit, the other reads as a native application and wants icons this project does not have.

**Sign out is not in the header.** It was a once-a-season action holding permanent primary navigation, and it was a form dressed as a link. It is on the account page, which is what the circle opens.

**Labels only.** A live figure per tab was drafted against §7's argument that all engagement pressure sits in the interface, and dropped: see revision note 11.

### Viewport strategy

**Mobile-first, with desktop treated as a wide tablet** — a constrained, centred column that expands moderately rather than a sprawling multi-panel layout.

This aligns usefully with the anti-AI-flag goal: grids of cards spanning a 1440px viewport are precisely the generated-dashboard look being avoided. A constrained measure forces typographic hierarchy to carry the information load.

**The qualifying bracket was the stated hardest visual problem in the project**, and it is solved — at 360px first, with desktop as a relaxation. See §4.7.

---

## 2. Game rules

### Lineup

**4 drivers + 1 team**, subject to:

1. Maximum one driver per team among the four driver picks
2. The team pick must not be a team already represented in the driver picks

With **20 drivers across 10 teams** (verified from the S12 season payload), that is C(10,4) × 2⁴ × 6 = **20,160 valid lineups**. Each player covers 5 of 10 teams — half the grid — so overlap on obvious picks is expected. Differentiation comes mainly from transfer timing.

**Do not hard-code 20 drivers or 10 teams.** That figure is a property of the current grid, not an invariant. Gen4 could bring an eleventh team, a third car, or a mid-season withdrawal. Constraint validation and the valid-lineup enumeration must operate over the actual roster derived from data. Treat 20,160 as a performance expectation only.

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

#### Three rules the counting rule does not cover

**Only the earliest unlocked weekend is editable.** If a player could set their meeting 9 lineup while meeting 8 was still open, meeting 9's cost would depend on a baseline that is still moving, and there would be no honest figure to show them while that was true.

**The cost baseline is the last snapshot from an *earlier* meeting, never the row being rewritten.** Changing your mind before the deadline is free however many times you do it. Costing against the last thing saved would make a player pay for reconsidering, and the transfer bank would depend on how often they opened the app.

**A late joiner's bank starts at one, not two.** Grace already gave them unlimited edits up to their own first deadline (below); arriving at their first charged weekend holding a full bank on top would pay them twice.

#### Two diffs, two questions — the distinction that caused four bugs

The counting rule above measures against the **cost baseline**. The editor also needs to answer a second question — *is there anything to save* — and that is measured against **what is stored for this weekend**. The two baselines differ exactly when a player has committed for the open weekend, which is most of the time they are looking at the screen.

They are two objects, and Phase 7 fixed the fourth place they had been conflated:

| Object | Question | Baseline | Where it may be read |
|---|---|---|---|
| `diff` | What does this cost? | Last snapshot from an *earlier* meeting | The budget block, and the past-grace confirmation summary |
| `unsaved` | Is there anything pending? | This weekend's stored snapshot, else the carried-forward lineup | Everything a player can act on: the "In" tags, the caution bar, the confirmation dialog, the picker's "Put back" list |

**The rule: anything in the editor a player can act on reads `unsaved`; only the cost figure reads `diff`.** Any new control has an obvious answer for which it wants, which is the whole reason for writing this down. §11 records all four instances.

**Consequence for the UI: the lineup editor is a staged draft with an explicit commit.** There is no legal intermediate state between "team E driver in" and "team E out of the team slot", so edits cannot be applied slot-by-slot against the server. The editor holds a draft lineup in the URL, shows live constraint validation and a running transfer cost, and writes a single snapshot on commit. Validate the same rules server-side on submit; the client-side check is convenience, never authority.

### Deadline

Lineup locks at the **first qualifying session of the meeting's first round**. One deadline per meeting.

Computed from the earliest `startTime` across the sessions of `type: "qualifying"` on the meeting's first round. Note that session times come from the events endpoint only — the season detail endpoint returns the calendar without them (§6).

**Store the computed deadline on the Meeting; do not derive it at request time.** Formula E schedules move. The deadline is computed at season sync, then persisted, along with `deadline_session_id` so the UI can name the session rather than showing a bare timestamp.

**The deadline is monotonic once published: a resync may move it later, never earlier.** Without this rule a schedule shift retroactively locks players out of a meeting they were still editing, with no way to explain what happened. An earlier session time found at resync is a sync conflict (§6): the meeting is left untouched and flagged.

**Rendered in the installation's display timezone, never bare UTC.** See §7.

### Season-start grace

Unlimited free lineup edits until the **first deadline of the season** (Jeddah, 18 December 2026). Transfer accounting begins from meeting 2. A player who joins later gets the same unlimited-edit grace up to their first locked deadline.

**Nothing that presents a cost may appear during grace.** No "In" tags against the cost baseline, no "This uses 3 transfers" in the confirmation, and the commit control says *Save lineup* rather than *Commit transfers*. The figure is not merely unhelpful there, it is false — nothing is spent — and it is the one number in the editor a player would act on. What changed still shows; only the price comes off.

### Absent drivers

A picked driver who does not appear in a session's results scores 0 for it. No substitution, no compensation.

If a driver leaves the grid mid-season (injury, contract change), the player must spend a normal transfer to replace them. **No free transfers**, deliberately: it avoids a special case, and it removes any route where a convenient absence hands someone an extra move.

**The roster is fully derived from API data.** No curated entry list, no admin-maintained "main driver" flag. One-off reserve drivers become pickable, and that is acceptable — the app must not assert who the regular drivers are, because it would eventually be wrong.

**Mitigation against misinforming users:** the driver picker shows rounds-participated alongside each driver, taken directly from `driver.teams[].participationRounds` (§6). A reserve who has appeared once is then self-evidently a one-off without the app claiming anything. From Phase 7 the picker also carries an info mark opening the driver's full profile and season history, which is the pre-season's only evidence about anybody.

**Pickable drivers come from seat entries, not results.** A driver appearing only in a rookie practice session has no seat entry and is therefore not pickable, which is the correct outcome — see the note on ingested stages in §6.

### Leagues

**Invite-based, multi-league** — built for medium-scale production, not just the initial friend group.

- Users may belong to multiple leagues simultaneously
- Leagues are created by a user, who becomes its admin
- Joining is by invite link or code
- One global league holds everyone; every other league is private
- A member cap bounds query cost

A single lineup per user per meeting scores into **every** league they belong to — league membership is a view over scores, never a separate scoring context. This keeps scoring O(users) rather than O(users × leagues), and it is also what makes joining a league late cost nothing: a March joiner brings their whole season with them.

**Leagues are durable across seasons.** A League row carries no `season_id`; season scoping applies to the standings computed over it. League administration lives on the membership row (a `role` column), not solely on `League.created_by_id`, so a league survives its creator deleting their account. See §7.

**Because leagues carry no season, they are the only part of the app that works before the calendar lands.** That is what the pre-season front page points at.

**The cap is a config constant, not a column.** `MAX_LEAGUE_MEMBERS` bounds query cost, and query cost is a property of the installation rather than of any particular league. It is enforced at join under a `SELECT ... FOR UPDATE` on the league row: counting and inserting are two statements, and two people taking the last slot at the same moment both pass a count taken before either insert.

**Invite codes are generated, not checked.** A SELECT that finds a code free and an INSERT that uses it have a gap between them. Generation loops inside a savepoint and lets the unique constraint arbitrate, which has no gap.

**Rotation is the only revocation.** There is no separate "closed" state: issuing a new code makes every link already shared dead, which is the whole of what revocation means here.

**If the last admin leaves, the earliest-joined remaining member is promoted.** A league with members and no admin has nobody who can rotate its code or remove anyone.

**The invite landing and the code form share one rate-limit bucket**, keyed on `CF-Connecting-IP`. Only a *missed* code counts: a member re-tapping their own working link is not enumeration.

**A pending invite expires.** A code followed by a signed-out visitor rides in the session and is consumed on the next successful authentication, but an invite followed yesterday must not silently join someone because they happened to reset their password today.

### Lineup visibility

**Hidden until lock, then visible to co-members.** One sentence, but two independent predicates, and they do different jobs:

| Predicate | What it is for |
|---|---|
| The meeting's deadline has passed | Load-bearing. It is what makes "no pre-deadline who-picked-what view exists at all" true, and it is the only thing that removes copying as a strategy. |
| The viewer and the subject share a league, and the subject is not hidden in it | A privacy scope. Once a deadline has passed copying is impossible, so this does no game-design work. |

Both are required; neither is sufficient.

**Enforce in the query layer**, not in a template. A locked/unlocked check that lives only in Jinja will leak through any JSON endpoint, HTMX partial, or friend-profile route added later.

The enforcement is structural rather than a matter of discipline: **no function returns another user's lineup without a viewer argument.** `app/lineups/service.py` reads the signed-in player's own lineups and takes a `user`; everything foreign goes through `app/leagues/visibility.py` and takes a `viewer` and a `subject`. `service.effective_snapshots` deliberately does *not* grow a viewer argument — the scoring pass must see everyone, and a scoring pass that *can* be filtered by a viewer is one that eventually will be.

Phase 7 added a second reader on that path: the friend profile's results fragment. It resolves the weekend through `player_profile` before rendering anything, so a weekend outside the visible list is unreachable there too.

**The null-deadline trap.** `Meeting.deadline_at` is nullable, and a null deadline means *not locked*. In SQL that falls out of three-valued logic, since `NULL <= now` is NULL and the row does not match. The Python spelling people reach for (`if not m.deadline_at or m.deadline_at <= now`) inverts it, and the naive comparison raises. Both cases are pinned by tests.

Consequences: friend profiles show only locked meetings; the Perfect Five appears only once results are in; and no pre-deadline "who picked what" view exists at all.

### The global league

**One league carries `is_global` and holds every user**, enrolled at registration. It is not an exception to the rule above: the co-membership clause is unchanged and simply true for everyone. There is no `is_global` anywhere in `visibility.py`.

Doing it as data rather than as a relaxed predicate buys four things: one clause that a future endpoint cannot get a public variant of; a real privacy control, since a member can withdraw; a reversible decision; and a table for a new user to appear on without anyone having to create a league first.

The member cap does not apply to it. Its table shows the top `LEAGUE_TABLE_MAX_ROWS` plus the viewer's own row.

### Hiding

**`LeagueMembership.hidden` is the opt-out, and it is a flag rather than a deleted row.** Leaving a league takes your read access with it; the account setting this backs says "stop showing me", not "stop showing me the table".

It is asymmetric on purpose. A hidden member still sees everyone else and still sees their own locked lineups; only their visibility to others is withdrawn. That is safe because every lineup reachable through the visibility layer is already past its deadline.

**A hidden member is excluded from a standings table entirely, including from their own view**, which is deliberately unlike the lineup case. A grid of lineups is a set; a ranking is an ordering, and an ordering that differs depending on who is looking makes "third" mean nothing.

The column is general, but only the global league's toggle sets it. Hiding inside a private league would remove the thing the league is for.

**Not-visible is 404, never 403.** A 403 confirms that the account or the league exists.

---

## 3. Scoring

Scored **per round**. A double-header meeting scores twice on the same lineup.

**There is one unit in this application and it is the fantasy point.** Formula E's own championship points are ingested and stored, because §6's payload sanity check compares against the published distribution and that check is what catches a truncated classification — but they are rendered nowhere. Two scoring systems side by side in a game about the second one is a category error the reader has to resolve on every row. The abbreviation is **FP** and it is defined once, in `app/meetings/display.py`.

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

**The bracket displays these per stage rather than cumulatively** (§4.7), so a driver's figures on screen add up to their qualifying total, and that plus the race table's FP is the round.

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

**`fastestLap.rank` marks the fastest lap among championship-eligible drivers**, so it silently reimposes the top-ten restriction. Measured across Season 12, it disagrees with the quickest `lap_time` on **eight of seventeen rounds**, and in seven of those eight the genuinely quickest driver finished outside the top ten (P19, P12, P12, P19, P18, P19, P16, P16).

The eighth, Shanghai R13, is a straightforward vendor error: Rowland (P8, 1:10.945) set the quickest lap and the `points` field credits him, but `rank` marks Vergne (P2, 1:11.394). Both were inside the top ten, so eligibility does not explain it.

So: **the fastest-lap point goes to the driver with the minimum `lap_time` across the race classification.** Store `fastestLap.rank` for reference; never score from it.

**One derivation, one star.** The classification's fastest-lap marker comes from `engine.fastest_lap_driver_ids` — the same function the score uses — so the row marked cannot differ from the row credited. A star in the display derived independently would be worse than no star at all. It is a set, so an exact tie shows two.

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

Without it, race scoring has no midfield resolution at all. Strip the rule out and the race gradient becomes P1 = 12, P2–P3 = 7, **P4–P10 = 2**, P11–P20 = 0. Seven consecutive finishing positions score identically. Places gained/lost is the only rule that resolves the middle of the field, so it is not an optional extra — it is load-bearing.

Structurally asymmetric by design: a front-row qualifier has no upside and up to −4 exposure, a back-row qualifier has +4 upside and no risk. This is the main tension in lineup choice and partly counterbalances the value of strong qualifiers.

**Grid position means the starting slot, after penalties.** A driver serving a five-place penalty genuinely starts further back and genuinely has more to gain. Do not substitute the qualifying result.

**DNFs punish themselves.** The API gives retirements ranked finishing positions (São Paulo's seven DNFs occupied P14–P20), so a retiring front-runner automatically takes the full −4. No separate DNF rule needed.

**Defensive handling.** If `gridPosition` is null or zero on a race result row (pit-lane start, data gap), score places gained/lost as 0 for that driver and log a warning. Never guess a grid slot.

**Magnitudes are provisional at ±4.** See the caveat in §9 about sprint races.

### Team scoring

**Half the sum of the team's two drivers' round scores**, including any negative places-lost values.

Keeps the team slot comparable in value to a driver slot, and creates a distinct judgement: you want a team whose *both* cars perform, which is a different call from picking one star.

Halves are permitted (drivers on 8 and 3 → team scores 5.5). Store as decimal; do not round, as rounding introduces a bias that needs explaining. `display.fmt` strips a trailing `.0` and keeps a genuine `.5`, because a Decimal's trailing zero is an artefact of arithmetic rather than a fact about the score.

**This is also why the team pick's two cars are marked in a results table** alongside the four driver picks: they are as much a part of the figure above them as the four are (§4.4).

### Scoring rulesets are versioned and snapshotted

Point values are not constants in code. They live in `app/scoring/rules.py` as a named, versioned ruleset, and the ruleset in force is recorded against each Round when the round is created — `Round.scoring_ruleset_version`.

§9 exists specifically to tune point values against real data, and the ±4 cap is explicitly provisional. Changing a value must never retroactively rewrite a completed round's score. Combined with the stored per-pick breakdown (§5), every historical score stays reproducible and rescoring stays idempotent.

**Every engine call passes `get_ruleset(round.scoring_ruleset_version)`**, never the default. A defect found in Phase 5 had `scoring_bridge` resolving to `CURRENT_VERSION`, which was harmless while v1 was the only version in play and would have been a silent rewrite of completed rounds at the first re-tune after Jeddah.

**The bracket's per-stage figures read the same ruleset object**, so magnitudes cannot drift there either; a test pins their structure (§4.7).

### Partial scoring

**A round is scored from whatever has landed, and marked provisional until every session it holds is in.**

Qualifying finishes hours before the race. Holding the score back until the round is complete would mean a Saturday morning where the game knows what happened and shows nothing, which is the opposite of what a fantasy game is for.

This is safe because of a property of the rules rather than of the code. Every fantasy point is additive within a session, and places gained/lost — the only rule that can go negative — needs the race and therefore lands atomically with it. So a provisional score is a **monotonically increasing partial sum**: it never revises downward.

The one thing that can move a stored score down is the provider correcting a classification, and that is a correction worth having.

**What makes a round complete:** its race results are in, and every scoring session it holds has been ingested. Deliberately *not* "and the bracket has the expected ten sessions" — the sync already raises `unexpected_session_shape` on a completed round with the wrong count (§6), and a second copy of that expectation in the scoring pass is how the two quietly disagree.

**Provisional is said out loud.** `MeetingRef.provisional` is true when a round is mid-score or when a double-header has only one round in, and the weekend view prints "Scoring so far. Not every session of this weekend is in yet." A half-scored weekend read as a finished one is the one way an honest partial sum misleads.

---

## 4. Views

| View | Route | What it answers |
|---|---|---|
| **Front page** | `/` | The weekend that is live, when the next one locks, what is left to spend, and where you stand |
| **Lineup editor** | `/lineup` | Pick and manage the five slots for the one weekend that is open |
| **Weekend** | `/weekend?m=N` | What you scored, per pick, with the classification and the bracket beneath |
| **Perfect Five** | `/weekend/perfect-five?m=N` | What the weekend was worth |
| **Friend profile** | `/players/<id>?m=N` | Another player's weekend, and their season |
| **League table** | `/leagues/<id>` | Season standings within a league |
| **League settings** | `/leagues/<id>/settings` | Members, the invite, the name, leaving |
| **Subject card** | a sheet, from any results row | What this driver or team scored *this weekend* |
| **How to play** | `/how-to-play` | The rules and the scoring, rendered from the ruleset |
| **About, privacy, terms** | `/about` `/privacy` `/terms` | What this is, what is held, what is agreed |
| **Driver / team profile** | a sheet, from anywhere | How this subject has scored this season, and in earlier ones |
| **Admin health** | `/admin/health` | Provider quota, worker liveness, scoring coverage, outstanding conflicts |

### 4.1 The lineup component — one component, three states

**An architectural commitment, not a stylistic one.** Four driver slots in a 2x2 grid, the team slot as a wider band beneath, identical geometry every time — so the arrangement itself carries meaning before any number is read.

| State | What it holds |
|---|---|
| `empty` | slots are empty; tapping one opens the picker |
| `edit` | slots are filled; tapping one opens the picker to swap |
| `scored` | slots carry a meeting total; tapping one discloses the breakdown |

Anything the component does not recognise renders filled and inert, which is what a locked weekend needs and cost nothing to add.

**Slot order never re-sorts by score.** A layout that reshuffles by performance cannot be read at a glance, which is the only thing this component is for.

**The team band is one primary with a thinner accent inside it**, not two equal stripes: at slot scale two equal stripes read as a pattern, a band with an accent reads as a livery. The team slot is the exception — it is both cars, so its stripes are equal.

**The car number is set large and barely inked behind the driver's name.** Formula E cars carry their numbers; borrowing that as a typographic ground gives the slot depth without a graphic, an icon or a gradient.

**A pending change is marked structurally** — heavy ink and an "In" label — never in the error colour. A transferred-in pick is the thing you wanted, not a fault, and sharing red with broken rules would empty red of meaning. The same argument produced `--caution` rather than a second use of red for unsaved changes (§1).

The component lives at `app/templates/lineups/_lineup.html` and is imported by five screens, not reimplemented.

### 4.2 Driver and team profiles

**One wide table**, not a split by contest: every scoring route as a column, every round as a row, totals in bold at the foot. The question the page exists to answer is "how has this driver scored across the season", and splitting qualifying from race gives two grand totals instead of one.

The first figure column is **FP**, not TP. "Total points" is a phrase this application has no use for, because there is only one kind of point here.

Eleven columns fit a 360px viewport at `--step-1` in condensed tabular figures — measured, not assumed. **What makes it readable is not the width but suppressing zeros**: nine columns of "0" is noise, and a blank makes the cells that fired legible at a glance.

Places gained and lost share one signed column. They are one mechanic with a sign.

A team profile shows both cars per round beside the team's own figure, which makes the half-sum rule explain itself.

**Below the table, season history**: one row per earlier season with its FP total, under a heavy rule because the unit is the same but the scope is not. Fantasy points only — there is no attempt to reconstruct a career from Formula E's own championship results, because the ruleset was tuned against Season 12's format, the duels qualifying it scores did not exist before Season 8, and a figure for Season 3 would look authoritative and mean nothing. This game starts counting when this game started. The current season is excluded: the table above already *is* that season, and repeating its total two inches lower invites checking arithmetic against the same figure.

**A profile answers even when the season has scored nothing.** Between the Season 13 sync and Jeddah that is every driver, and it is exactly the window in which "how did this one do last year" is the only question worth asking. An earlier version returned nothing there, so the info mark would have opened nothing during the one period it is most useful.

Profiles open over whatever is already on screen and close by dropping a URL parameter, so closing one returns the reader to the row they tapped. They are reachable from a classification, a bracket row, a breakdown, and — from Phase 7 — the lineup picker.

### 4.3 The editor

**The draft lives in the query string.** `?d=4,9,12,17&t=3` is the whole editor state. That means every constraint check and every transfer cost on screen is computed by `app/scoring/lineups.py` — the same module the server enforces on commit — rather than by a mirrored copy in JavaScript that drifts the first time a rule changes. The cost is a round trip per tap, which HTMX hides and which this app can afford at twenty drivers.

**The interface never prevents, it explains.** Nothing in the picker is disabled. An earlier version greyed out options that would break a constraint and created a trap: a player holding a Citroën driver could not select Citroën in the team slot, even though the reverse order — team first, then driver — was allowed. Same destination, same two-slot cost, arbitrary forced order. So the note replaces the block, and a forced relocation can be approached from either end. This is also required by the rule in §2 that a forced relocation has no legal intermediate state.

**An unaffordable draft is a broken rule like any other**, and reads in the same place and the same voice as one.

**A state the lineup is in is stated once, above the component, at one of two levels.** `error` is a broken rule and blocks the commit; `caution` is unsaved work and blocks nothing. Two bars never stack — a broken rule is the thing to act on first — and neither appears while the draft is incomplete, because the slot counter already says that.

**One swappable region, no fragment template.** The editor is wrapped in an element carrying `hx-boost` with `hx-select`, so every link inside keeps a working `href` and the page functions with JavaScript off; with it on, HTMX fetches the same URL and swaps the region in place. There is no separate fragment route, and therefore no fragment that can drift out of step with the page. **The cost of that decision is that every descendant inherits the region's targeting** — see §11.

**Development clock override.** Every deadline in the backfilled Season 12 is in the past, so the editor has nothing to open against the only real data that exists. `FANTASY_NOW` in `.env` moves the app's clock. It is excluded under test, logs a warning on every request that uses it, and is deliberately **not** gated on `app.debug`, which is set at different points under `flask run`, gunicorn and a shell.

### 4.4 The scored view — one shape, three pages

`/weekend`, `/players/<id>` and `/weekend/perfect-five` are the same screen with different contents, and that is enforced rather than coincidental:

```
  meeting nav        arrows, venue, round context
  verdict            one label, one figure
  lineup             the component in `scored` state
  breakdowns         disclosed on tap, one per slot
  Perfect Five link  quiet, right-aligned
  Results            a disclosure: classification or bracket
```

**The verdict's label is the only variable** — `Your weekend`, a player's username, `Perfect Five`. Which is why the friend profile has no heading: the label already says whose weekend it is, and an `h1` above it said the same thing twice while pushing the component down the page. The season total moved below the lineup, where it is a footnote rather than a headline competing with it.

**Arrows where you can move, the same bar without them where you cannot.** The front page shows the one weekend that is live and the editor the one weekend that is open — §2 permits editing no other — so arrows there would advertise navigation the application refuses. `meeting_masthead` renders the identical four-child structure with empty spacers in the arrow slots, so those two screens keep the geometry without the affordance. Spacers rather than flat arrow glyphs, because a flat arrow means "you are at the end of a list" and there is no list there to be at the end of.

**The mark belongs to the lineup rendered directly above it.** Six drivers, not four: the four picks plus both cars of the team pick, because the team slot scores half their sum (§3). On your weekend that is your six; on a friend's profile it is theirs; on the Perfect Five it is that lineup's own. Nothing decides "yours" versus "theirs" — the lineup on screen does, and `marked_drivers` is one function.

This is also what makes the mark safe. A reader browsing back to Jeddah in April sees the picks they had in December, not the ones they hold today, because the marks and the slots are the same six picks forty pixels apart.

**Three post-lock states, not one:** scored with picks; locked with picks and nothing scored yet, which renders the five slots inert; and locked with no lineup at all. A page that renders nothing cannot tell "you had no lineup" apart from "no results yet", and those are opposite things.

**A lineup appears only after the deadline.** Not privacy about yourself — it is that a second screen rendering an editable lineup is a second editor, and the two would drift. Before lock the page is the countdown and a link.

**One results context, six callers.** `results_context(meeting, sequence, yours, base)` builds the disclosure for three pages and their three HTMX fragments. `base` is the only thing that differs, and it is what keeps a reader who switches round on a friend's profile from being thrown onto `/weekend`.

### 4.5 The Perfect Five

**The four best-scoring drivers of a weekend and the best-scoring team.** Not the best *valid* lineup, which is what §4 and §10 said until Phase 7.

The brute force over all 20,160 legal combinations produced a page a reader could not parse: a driver who outscored three of the five was absent because a higher-scoring team-mate had taken his team's slot, and no caption fixes that — you have to hold the constraint set in your head to understand why. It also tied constantly: six of seventeen Season 12 rounds, across as many as eighteen lineups, so "this is the answer" was rarely true.

Three things follow from the change:

**Ties cannot reach the page.** The order is total, then the driver's best finishing position across the meeting, then the id. Two drivers cannot share a finishing position, so the second key settles every tie the first leaves. The third exists only so a driver who never finished still sorts deterministically — `seat_entries()` has no `ORDER BY`, and before this the winner of a tie could differ between two requests for the same weekend, which is what made a starred pick sometimes fail to appear on its own page.

**The star means one simple thing**: this pick was one of the five best of the weekend. Set in exactly one place, `mark_best`, and **compared within kind** — drivers and teams are separate tables with independent key sequences, so at this grid size driver 4 and team 4 are the same integer (§11).

**The benchmark is given up deliberately.** This is not a lineup anybody could have fielded, and the page says so in a sentence. There is no "you scored 34 of a possible 61": that is a scoreboard telling someone off, and this application has no email, no reminders and no nagging anywhere else. The front page says what you scored; this page says what the weekend was worth. Two facts, not a verdict.

Its own route, reached by a quiet right-aligned link below the lineup and by the star inside a breakdown. Not a section of the weekend page: "what was possible" is a question asked *after* reading your own score, and in the headline it answers a question nobody asked. It refuses to render before the deadline, because a best lineup published early is an answer key.

`dream_team` and `valid_lineups` stay in `app/scoring/lineups.py`: §9's question 7 measures the tie rate over legal lineups, and that is still the right question to ask there.

### 4.6 Results

**The classification is P / Driver / Grid / Δ / Best lap / FP**, with a star on the quickest lap of the race and a rule in the margin against the six rows that fed the lineup above.

**FP is this race's fantasy points, not the driver's round total.** Every other cell in the row is a fact about this race, and a figure that quietly folded in Saturday's qualifying would make the row internally inconsistent — a reader checking P8's 2 against the points-finish rule would find it did not add up. The weekend total lives in the breakdown, where the two contests are summed and labelled.

A zero is printed rather than suppressed. §4.2 suppresses zeros across eleven columns because nine noughts drown the two cells that fired; in a single column a nought is the answer and a blank would read as missing data.

Before a weekend has been raced the disclosure shows the schedule instead, in the display timezone with the zone named once above the list.

### 4.7 The qualifying bracket

**The hardest visual problem in the project (§1), and the open risk Phase 3 recorded rather than resolved.** Twenty drivers, two groups of ten, the top four of each into four quarter-finals, two semis and a final. Drawn as a conventional left-to-right tree that is four columns wide before a name is set, and a phone has room for about two.

**So it is not drawn as a tree.** It is read down the page in the order it happened, each stage its own small classification, and the tree structure falls out of two things that need no lines: a driver only appears in the next stage if they won this one, and the losing row of every pair is dimmed and terminal.

That is close to the linear stage list Phase 3 shipped as an interim — which turned out to be the right representation. What it was missing was not a diagram; it was **what each stage was worth**.

Four decisions:

**Points per stage, not per driver.** A driver's qualifying total accumulates across the bracket, so a running figure on each row would invite the reader to add rows that are already summed. Each row carries what *that stage* awarded: 2 to reach the Duels, 1 for each duel won, 3 more for pole. Summed per driver they equal the qualifying total in the profile, and added to the race table's FP they equal the round. Every figure on screen is reachable by addition from figures also on screen.

The Final winner's cell therefore reads 4, not 1 — the duel win plus the pole bonus. Splitting them across a row is fussier than the thing it clarifies.

**Elimination is ink, not opacity.** Loser rows drop to `--text-low` at regular weight. Opacity would dull the team stripe, and the stripe is the recognition aid — it has to stay at full strength whether or not the driver went out. No strikethrough either: it reads as deleted, and these drivers did compete.

**Deltas below the leader.** `+0.161` is the fact a reader wants from a duel; the absolute is noise once the leader's time is on the row above. Parsed, never string-compared.

**The stage heading is also the column rubric**, taking the row's own grid so the labels sit exactly over the columns they name. A separate header row would be a third heading level above ten rows; putting the labels on the section title would leave Group B's rows twelve lines below the only place that says what FP means.

**How the figures are derived, and the guard on it.** From position plus the round's own recorded `ScoringRuleset`, not from the stored components — `ScoreComponent` records which *rule* fired and not which session, so attributing a duel win to QF3 rather than SF1 would mean parsing a detail string written for humans. That means the structure of the qualifying rule is written down in two places. Magnitudes cannot drift, because both read the same ruleset object. Structure can, and a test asserts the bracket's per-driver totals equal `engine.score_qualifying`'s own over the same sessions. Same guard §5 puts on `transfer_cost` and `scoring_provisional`.

**It needed no new token and no new primitive** — only an arrangement of `.ruled`, the team band and the three rule weights, which is the demonstration Phase 3 recorded as owed. The three weights carry the hierarchy exactly as `tokens.css` argues they should: hairline between rows, mark rule at the group cut and between duel pairs, heavy rule above each section heading.

### 4.8 The subject card

**A driver's name in a classification or a bracket row opens what they scored this weekend**, not their season. A reader who taps a row inside a specific round is asking about the weekend they are looking at; the season is one further tap, on the card's own info mark. Three depths in the order the questions are asked: the round on screen, the weekend containing it, the season containing that.

**Meeting-scoped, not round-scoped**, even though the tap happens inside one round's table. A double-header would otherwise give the same driver two different cards depending on which round's classification you came from, with nothing on either saying which — and the lineup slot above would show a third figure, their sum.

It is the same macro over the same object as a lineup slot, which is enforced rather than coincidental: `view._driver_pick` and `view._team_pick` were extracted out of `score_meeting` so a card and a slot cannot drift. `subject_meeting_score` builds a one-pick `RoundBreakdown` per round and hands it to `aggregate_meeting`, so there is no aggregation logic in the new path at all.

`RoundScore` is user-independent, so the card needs no viewer argument — unlike anything that reads a lineup. Its fragment route answers 204 on any miss, because an error document swapped into a dialog host is worse than nothing; the *reason* goes to the log, for the reason §11 records.

### 4.9 The static pages

Four, written because registration is public and friends arrive in December knowing nothing about scoring.

**`/how-to-play` renders every figure from `app/scoring/rules.py`.** The qualifying gradient, the race table and the worked-example totals are all derived. §3 versions the ruleset precisely so the post-Jeddah re-tune does not rewrite December, and a hand-typed page of point values would start lying the day that re-tune ships. This is the one place `get_ruleset()` with no argument is correct: the page describes how a lineup picked *today* will score.

**A rules page states rules.** No rationale, no design intent, no reassurance. The reasons live in this document.

**`/about` states what the app is**, credits the provider, states non-commercial — which the free tier requires — and disclaims affiliation with Formula E, the FIA, ABB and any team or driver, with trademarks used only where necessary to describe the championship.

**`/privacy` and `/terms` are written to UK GDPR Article 13 and to the Gambling Act's negative**: the controller named, the lawful bases given as contract and legitimate interests, every processor named including Cloudflare, the EU database location stated, both cookies described with a note that there is no banner because there is nothing to consent to, the ICO route linked, a minimum age of 16, and no entry fee and no prize said explicitly.

Headings carry ids so a section can be linked to. No visible table of contents: eight short sections on a phone would put a screenful of links in front of the answer.

### 4.10 The league pages

**`/leagues/<id>` is the table. Administration is `/leagues/<id>/settings`.** They were two visits wearing one URL, and only one of them happens on a Sunday night.

The split removed a duplication rather than hiding one: the membership list was the standings table's own people in a different order, one screen apart, and everything unique to it — join dates, who is hidden, the remove control — is administration.

Settings is visible to every member, not only to admins. A member needs the code to invite someone, wants to see who is in, and must always be able to leave; which controls appear inside each band is what `membership.is_admin` decides. Every mutating control returns to settings, except leaving, which returns to the index because the league it acted on is no longer readable.

**The league list answers "where am I", not "how many are we".** A member count is a property of the league; this page is a list of the reader's own leagues. Once a weekend has scored the position leads and the count moves under the name, where "of 50" still says whether there is room for a friend.

**One meaning per signal.** Weight in a standings table means `.is-yours` and nothing else. The Points column used to carry semibold on every row to say "this column decides the order", so the viewer's row was bold because it was theirs and everyone's points were bold because they were points, and neither could be read. Points keeps prominence through ink instead.

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

`Meeting.sequence` is never surfaced as a headline. It is derived bookkeeping, so a regrouping would renumber every later weekend while the round numbers stayed fixed. The venue name leads; round numbers give the context; the sequence appears only in the weekend list, where it reads as ordering.

### Round numbering

**Not in the payload.** Round numbers are inferred from position within `season_detail.schedule`, which is also what the provider's `participationRounds` arrays refer to — so calendar order is used as given rather than re-sorted by date, since re-sorting would desynchronise the two.

Once assigned, a round number is immutable: a resync that would renumber an existing round raises a sync conflict rather than updating.

### Round format — new for Season 13

`Round.format` with values `eprix` and `eprix_unleashed`.

Derived at sync by rule: a single-header meeting's only round is `eprix`; in a double-header, round 1 is `eprix_unleashed` and round 2 is `eprix`. **Admin-overridable via `Round.format_locked`** — the regulations say double-headers "typically" carry one of each, and typically is not always.

**Gated on season.** The rule applies from Season 13 (ending year 2027) onward. Season 12 ran two identical races per double-header, so applying it to the backfill would label half the calendar as sprints that never happened.

### Session stage

`Session.stage` and `Session.stage_index` are stored separately: "Qual Quarter-Final 3" becomes `stage="quarter_final", stage_index=3`, derived once at ingest from the session name.

Splitting them means a reshaped bracket — Formula E ran four qualifying groups before 2022 — is a data change rather than a migration. It also means the scoring engine never re-parses a session name, and it is what lets the bracket sort into reading order without touching a string.

### Lineups: store snapshots, not deltas

**The most important architectural decision in this project.**

Store a **complete lineup snapshot per (user, meeting)**. Treat the transfer allowance as a *validation rule* between consecutive snapshots, not as the stored truth.

Rationale: with a transfer bank, a lineup at meeting 8 is otherwise only knowable by replaying meetings 1–7. Replaying a sequence to fix a scoring bug in March is fragile. With snapshots, every meeting is independently recomputable, the transfer bank is derivable, and a season history is a straight query.

#### The game schema

`LineupSnapshot` and `LineupPick`, with four decisions worth recording.

**Snapshots are sparse.** A row exists only where a player committed. The effective lineup at meeting N is the latest snapshot at or before N — one indexed query — so a player who has not touched the app since meeting 3 still has a lineup at meeting 7, and it is meeting 3's. The alternative, a job materialising a carried-forward row for every player at every deadline, writes rows for people who have stopped playing and buys nothing the ordering query does not already give.

The weekend view says so when it applies: "Carried forward — no changes were committed for this weekend." A figure against a weekend a player never touched reads as a mistake unless the page explains it.

**The five picks are rows, not five columns.** The four drivers are a set, so columns would let a reordering read as four transfers. Rows also give `PickScore` somewhere to hang. A driver pick and a team pick are one table with two nullable foreign keys under a check constraint, rather than a polymorphic subject id: real referential integrity in both directions, and readable joins. `ondelete` is `RESTRICT` on both. **No slot index** — storing an ordinal would invite a diff that charges for reordering.

**The slot diff is stored on the snapshot.** It makes the bank a running sum rather than a re-diff of the whole season, and a test asserts the column always equals a recomputation. It stores what *changed*, not what was *charged* — whether a diff was charged is a function of the player and the calendar, not of the row. A grace-period commit stores zero anyway, because a grace weekend is by construction the player's first and there is no earlier snapshot to diff against.

**`season_id` is denormalised onto the snapshot**, though `meeting_id` scopes it transitively. The app runs across seasons and "this player's season" should stay a single-table query.

**The bank, the grace boundary and the open weekend are derived, never stored.** Storing any of them would create a second source of truth that drifts.

### Scores: two tables

**`RoundScore` is the truth, and it is user-independent.** One row per `(round, subject)`, where a subject is a driver or a team: thirty rows a round at the current grid, whether the league has three players or three hundred. "Cassidy reached the Duels and finished P4" is the same sentence for everyone who picked him, so it is written once. It carries the total, the component breakdown as JSONB, the ruleset version, and nothing about any player.

That property is what makes half of Phase 7 free. The classification's FP column, the Perfect Five, the driver profile and season history are all reads over these rows, identical for every reader, and none of them needed a migration.

**`PickScore` is the projection onto players.** `(user, meeting, round, kind, subject)` carrying a number and two pointers — to the snapshot that was effective, and to the `RoundScore` the number came from. A league table is one `GROUP BY` rather than a lateral join against sparse snapshots, and "which lineup earned this" is stored fact rather than a re-derivation months later.

**The property that makes the per-user materialisation safe:** a snapshot may only be committed for the *open* meeting (§2), so a lineup can never change after its rounds are scored. Nothing a player does invalidates a `PickScore`. Only a rescore does, and a rescore rewrites both tables together.

**`participated` is a stored column, not an inference.** A driver who raced and scored nothing and a driver who was not on the grid both end up at zero with an empty breakdown, and §4.2 suppresses zeros precisely so the cells that fired stay legible — which only works if "did not take part" renders as a blank rather than a nought.

**Every subject gets a row, including one that scored nothing.** The subject set for a round is the union of three sources: the roster, whoever appears in results, and whoever any player still holds. The third is why a pick can never end up with a `PickScore` pointing at nothing.

**`Round.scored_at` and `Round.scoring_provisional`** are the dirty check and the partial-scoring marker. A round needs scoring when `scored_at` is null or older than the latest `results_ingested_at` among its sessions. That is the gate the poller tests on every tick.

`scored_at` is also what the meeting nav reads to decide whether a weekend has been scored. An earlier version asked whether any session had results, which diverged the moment partial scoring shipped: a Saturday weekend with qualifying ingested and no race has results and no scores.

**Rescoring is delete-and-rewrite inside one transaction**, not an upsert. Scoring is a pure function of the ingested results and the recorded ruleset, so wiping the round is the only version that cannot leave a stale row behind. Idempotent means same inputs, same outputs; it does not mean numbers never move.

**Reading them back is shaped like the engine.** `app/meetings/reads.py` returns objects with the same attributes and methods `app/scoring/engine.py` produces, so the display code cannot tell a stored score from a fresh one.

### Leagues

`League.is_global` with a partial unique index (`WHERE is_global`) so at most one such league can exist. Its invite code is the sentinel `GLOBAL`, which contains O and L — neither in `INVITE_CODE_ALPHABET` — so a generated code can never collide with it.

`LeagueMembership.hidden`, the opt-out described in §2.

Migration `0006_global_league` also creates the league and enrols every existing user. The application carries `ensure_global_league()` alongside it, because the test suite builds its schema with `create_all()` and never runs a migration — without it the entire visibility layer would be untestable.

**No `joined_at` scoping anywhere.** Standings are season totals for current members, per §2. This removes an exploit: if a table were scoped from `joined_at`, a player having a bad season could leave and rejoin to wipe it.

### Standings

One aggregate query grouped by `(user_id, meeting_id)`, joined to `league_memberships`, filtered to locked meetings, pivoted in Python. That one pivot yields totals, per-weekend figures and position movement without a second round trip.

A join rather than `user_id IN (...)`: the global league has no member cap, and an IN list is the shape that stops working first.

**Provisional scores are included and marked. Ties share a position and sort by username within the tie.** No countback — the game has no tiebreak rule and inventing one is worse than showing equal scores as equal.

**A position is computed over the whole table and then one row is read**, for the front page's per-league standing. At friend scale it is a handful of small aggregates. The replacement when that stops being true is a counting query, not a cache: a cached position is wrong for as long as it is stale, and a league table is read on exactly the days it moves.

### WorkerRun

One row per background job execution, for two jobs in one table. Diagnostic for §10's admin page, and the only place a monthly quota can live — the worker is a process that lives for one tick, so an in-process counter would never count past a single run.

Rows are written only when a run does something, plus a heartbeat at most once an hour. Pruning never deletes an unfinished row: a row with no `finished_at` is the only evidence a crash leaves behind.

### No migration in Phase 7

**`0006_global_league` is the last migration in this project to date.** Everything the visualisation phase added — the weekend view, the bracket, the Perfect Five, personal marking, season history — is a read over rows that were already being written. Worth stating explicitly because it was not a constraint anyone imposed; it fell out of `RoundScore` being user-independent and carrying its own breakdown, which was the Phase 5 decision that paid for the whole of Phase 7.

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

A 403 is ambiguous and must be classified: an HTML body naming error 1010 is a CDN refusal (`ProviderBlockedError`), a JSON body is an API credential failure (`ProviderAuthError`).

**Risk:** a CDN blocking a plain server-side client on a tier documented as server-side-only is a reliability warning sign. **Mitigation: provider abstraction layer from day one** (`app/providers/`, §12) — implemented, with `base.py` defining normalised dataclasses and a `ResultsProvider` protocol so nothing downstream sees a vendor payload.

### Rate limiting — undocumented, real

The free tier returns **HTTP 429 at roughly two sustained requests per second**. Nothing in the documentation mentions it; it surfaced during the S12 backfill, where five sessions failed after exhausting their retries.

- `OCB_MIN_REQUEST_INTERVAL_SECONDS` throttles the steady rate. **1.0 is the working value**; 0.5 triggers 429s during a long run.
- A 429 backs off far longer than a transient 5xx — 15 seconds scaled by attempt — because retrying in one second simply spends another call against the same window.
- `Retry-After` is honoured when present.
- A failed session is never stamped `results_ingested_at`, so re-running the backfill retries exactly the failures and skips everything already stored.

### Live polling — the rule this section states, inverted

**During a race weekend the poller does not check session status before fetching.**

Session status arrives only on `/events`, which cannot be filtered by season. Refreshing it costs four calls. So checking first costs **five calls per attempt** where guessing costs **one**. The original rule was written for the backfill, where you face 187 sessions and have no idea which have run; during a weekend the poller already knows, from the schedule it stored at sync, that a session was due to finish twenty minutes ago.

Two consequences, both handled in `sync_session_results(speculative=True)`. The stored status is stale by definition on that path and is not consulted. And an empty classification means *not ready yet* rather than *ran and nobody finished* — so it must not stamp `results_ingested_at`. A 404 is treated identically, because which shape the provider uses for an unpublished session is **still unknown**: Season 12 was finished and Season 13 unpublished when this was written. Jeddah is the first observation.

The four-call `/events` walk still happens, but as a check for *schedule changes* rather than as a liveness mechanism — daily, and every few hours when a session starts within 36 hours.

#### The budget

| | Calls |
|---|---|
| Season syncs (3 × 6) | 18 |
| Result fetches, 20 sessions × ~4 attempts | 80 |
| Slack for retries and misses | ~50 |
| **Weekend total** | **~150** |

A worst-case month is roughly 700 against 7,500. **Under 10%.** The binding constraint is the ~2 requests per second ceiling, not the monthly quota.

Off-season the cost is **one call a day**: `resolve_season` pages `/seasons`, finds no 2027, and raises before spending anything on season detail or the events walk. **That is the state production has been in since Phase 5 shipped in August**, under the cron entrypoint since 21 September, and the weeks between that and Jeddah are the evidence that the worker idles correctly.

#### How the poller stays quiet

Every tick opens with a query that costs nothing: is there a session whose scheduled end has passed and whose results are not in? Off-season the answer is no and the tick spends nothing.

| Since scheduled end | Behaviour |
|---|---|
| < 3 min | too early; results are never up instantly |
| 3–30 min | attempt every tick (five minutes) |
| 30 min – 6 h | attempt on the first tick after each 15-minute boundary |
| > 6 h | stopped, and reported as stale on the admin page |

**A tick is a process.** The worker runs as a cron job and exits (§7), so nothing in the poll may be remembered in memory between ticks. The patient phase is therefore derived rather than recorded: boundaries are counted from the end of the eager phase, and a session is attempted on the tick whose window contains one. Whatever phase the cron runs at relative to a session's end, that is exactly one attempt per interval; a skipped run misses one attempt and the next boundary makes it up. `POLL_INTERVAL_SECONDS` must equal the cron interval, because the arithmetic counts ticks by it and the process cannot read its own cron expression. `tests/test_worker_cadence.py` pins it.

A stale session leaves its round provisional until `flask backfill-results` fetches it. That remedy is manual on purpose.

**A monthly ceiling is checked before any job that would spend a call**, summed from `WorkerRun`.

**The worker targets the season by ending year, derived from the date** — from August onward it is next year's. So it asks for 2027 daily, logs "not published yet", and picks Season 13 up the moment the provider publishes it. Nobody has to watch for the UUID.

### Verified quirks

Probed 14 August 2026; corrected and extended 18–19 August 2026 against a re-fetched corpus and a full Season 12 ingest.

| Quirk | Detail |
|---|---|
| Three envelope styles | `/events` → `{data, meta}`; `/seasons/{id}` → bare object; `/results` → bare array. Normalised in the client layer. |
| Unknown params silently ignored | `?season=`, `?seasonId=`, `?perPage=` return **byte-identical** unfiltered responses with HTTP 200 — verified by hash. **Never treat a 200 as proof a filter applied.** Only `limit` and `page` work. |
| The events collection cannot be filtered | 165 events across all 12 seasons, no server-side season filter. A season's session times require paging the whole collection and matching client-side. Four calls at `limit=50`. **Season sync is inherently a two-step operation.** |
| Pagination | `?limit=` and `?page=` work. `meta` = `{page, limit, total, totalPages}`. Default limit 20. |
| Seasons UUID-keyed | `/seasons/2026` → 400 "uuid is expected". `/seasons` gives the year → UUID index. |
| **Season `year` is the ENDING year** | S12 ran Dec 2025 – Aug 2026 and is keyed **2026**. S13 will be **2027**. Reading it as the starting year silently returns the wrong season. |
| **Season 13 not yet published** | `/seasons` runs 2026 back to 2015 as of 23 Aug 2026. `status` and `roundCount` are null for every season, so year is the only usable selector. |
| **`session.type` has four values** | `practice`, `qualifying`, `race`, **`other`**. Season 12 round 3 carries a "Rookie Free Practice" typed `other`. Season 13's shakedown day will most likely arrive the same way. |
| **Sessions use `startTime`/`endTime`** | Events use `dateStart`/`dateEnd`. Reading the event's names at session level yields a null deadline. |
| Sessions carry their own status | `scheduled` \| `ongoing` \| `completed`. |
| **Qualifying rows omit `points` and `status`** | Absent keys, not null ones — subscripting raises `KeyError` on nine of the eleven sessions in a round. `gridPosition` by contrast is present-and-null there. Read every field with `.get()`. |
| **`driver.code` is null for 16 of 20** | **Key on `driver.id` (UUID)**, label with `lastName` plus `number`, treat `code` as decoration. |
| **`gridPosition` is the post-penalty starting slot** | NOT the qualifying result. Correct for places gained/lost; wrong for anything asking "who took pole". |
| **`fastestLap.rank` is eligibility-restricted** | Marks the fastest lap among top-ten finishers. Disagrees with the quickest `lap_time` on 8 of 17 S12 rounds. Store it; never score from it (§3). |
| Type inconsistency | `position` is a string (`"1"`), `gridPosition` an int (`5`), `points` a string decimal. Cast on ingest. |
| **`displayTime` has a variable shape** | `"1:01:13.217"` over an hour, `"59:23.013"` under. Never split on `:` expecting three parts — the 30-minute E-Prix Unleashed will be sub-hour every time. |
| `team.color` unreliable | Andretti and Jaguar both `000000`; Nissan has a real value. Not a usable palette. |
| Season detail lacks sessions | `/seasons/{uuid}` gives calendar + standings but no session times. |

### Endpoint strategy

- **`/seasons`** — year → UUID index. Resolve the season by ending year.
- **`/seasons/{uuid}`** — full calendar plus driver and team standings in one 13.7KB call.
- **`/events?limit=50&page=N`** — session times and IDs. Filter client-side.
- **`/events/{id}/sessions/{id}/results`** — per session.

**Only qualifying and race sessions are ingested.** Practice teaches the game nothing, and `other` covers cases like Season 12's Rookie Free Practice — a session full of drivers who are not on the grid. Ingesting it would put test drivers in the results table and corrupt any "who raced this round" query. Ten calls per round rather than eleven.

### `participationRounds`

It lives **inside `driver.teams[]`**, not at driver level, and it is an **array of round numbers**, not a count. Being per-team, a mid-season driver switch is represented correctly — two entries with disjoint round arrays. It is the source for the driver picker's rounds-participated figure.

It remains a live counter that grows during a season, so **it is not roster truth** — a driver who has not yet raced has an empty array. Use it for display, never to decide who is on the grid.

### Sync conflict policy

A resync must be trustworthy enough to run unattended twice a day, and must never half-apply. Changes are classified, and **each meeting syncs in its own transaction**.

**Applied silently:** a new event appearing, a meeting gaining a round, a session time moving later, a name or status change, a result arriving.

**Skipped and flagged:** a deadline that would move earlier (the monotonic rule in §2), a meeting losing a round, a round moving between meetings, a round being renumbered, a session count that does not match the expected bracket shape on a *completed* round, an unrecognised qualifying session name.

An unsafe change rolls back that meeting untouched and records a `SyncConflict` row; the remaining meetings apply normally. Conflicts deduplicate on a fingerprint. The admin page lists outstanding conflicts; a clean run shows nothing.

### Payload sanity check

A completed session returning a partial classification is the failure worth catching: nothing errors, the rows land, and a driver quietly scores zero for a race they finished. The check compares the provider's own `points` against the published championship distribution.

**This is the only consumer of `Result.points` and the reason it is stored at all** (§3). Reported as warnings, not refusals.

Pole detection for the check uses the **Qual Final winner**, not `gridPosition`. **Season-scoped**: skipped from Season 13, where qualifying awards championship points on a sliding scale and no replacement expectation exists yet.

Run against Season 12, the check surfaced exactly two real discrepancies across ~340 race rows — both at Shanghai R13, both traceable to the `fastestLap.rank` error in §3.

### Data quality

Season 12 as ingested: 11 meetings, 17 rounds, 187 sessions, 880 result rows, 20 drivers, 10 teams, 20 seat entries, zero sync conflicts.

**Action:** spot-check driver–team pairings against a trusted source. Small vendors get lineups wrong; Cassidy at Citroën is worth an eyeball.

### Season 13 sporting changes — effect on ingest

1. **Qualifying now awards championship points.** The top eight score on a sliding scale, up to roughly 105 points across the season. **This breaks the Appendix A ingest sanity check.** It is already gated on season; write a replacement expectation once a real payload is available.
2. **Double-headers run two different race formats.** Race 1 is `E-Prix Unleashed` (30 minutes, high downforce, no Pit Boost, six-minute attack mode); race 2 is a standard `E-Prix`. See `Round.format` in §5.
3. **A shakedown day precedes each weekend.** Expect unfamiliar entries in `schedule[]`, most likely with `type: "other"`.

Calendar facts for S13: 21 races across 13 locations, eight double-headers (Jeddah, Monaco, Berlin, Zandvoort, Brands Hatch, Jarama, Shanghai, Tokyo), new venues at COTA, Zandvoort and Brands Hatch, Miami returning. **The calendar is not frozen** — Mexico City is the stated fallback opener if Jeddah is judged unsafe.

---

## 7. Infrastructure

| Item | Decision |
|---|---|
| Domain | `fe.kitsniff.com` via Cloudflare CNAME |
| Hosting | **Separate** Railway project with its own Postgres instance |
| Repo | Fresh repo, not a fork of `f1-predictions` |
| Local dev | Raspberry Pi (Singularity), Debian 12, `~/projects/fe-fantasy` |
| Python | **3.11.2** — no PEP 695 generics, no `type` statement, no 3.12+ syntax. Pinned for Nixpacks via `.python-version`. |
| Postgres | **18.x in both environments** — local 18.4, Railway 18.6. Same major version, so `pg_dump` restores in both directions. |
| DB driver | **psycopg 3** (`psycopg[binary]`), URI scheme `postgresql+psycopg://`. Not psycopg2. |
| Auth | Separate account system. Keep the `User` model shape close to the F1 app so a future merge or SSO handshake stays cheap. |
| Stack | Flask, SQLAlchemy 2.x, Alembic/Flask-Migrate, HTMX, Jinja2, Flask-WTF, Gunicorn, pytest. The worker is a Railway cron job, not a scheduler library |
| Email | Resend, **password reset only**. No deadline reminders, no digests, no notifications of any kind. |
| Season scoping | `season_id` on every season-scoped table from day one. Leagues are the exception. |

**Consequence of the no-email policy:** all engagement pressure sits in the interface. The deadline state, unused transfer count, and "your lineup is unchanged since last meeting" condition need to be prominent on first load — there is no external nudge. This is workable precisely because the fantasy model degrades gracefully: a forgotten meeting still scores, so a missed reminder is not a lost player.

It is also why the app never nags. There is no "you scored 34 of a possible 61" anywhere (§4.5): with no email to be resented, the interface's tone is the whole relationship.

### Display timezone

**Every datetime is stored UTC and rendered through one filter.** `DISPLAY_TIMEZONE` in `app/config.py`, env-overridable, defaulting to `Europe/London`. `app/localtime.py` registers `local` and `local_short` as Jinja filters and `zone_label()` as a global.

**One timezone for the installation, not one per user.** Every player is in the UK. A per-user column would be a migration, a settings form and a preference nobody would ever change, to solve a problem that does not exist. The config value is the escape hatch if that stops being true.

Season 13 runs 18 December to 25 July, so half the calendar falls inside British Summer Time. `%Z` renders GMT or BST from the zone itself, so nobody has to remember which side of the clock change a date falls on and nothing needs updating twice a year. A deadline shown an hour early is the kind of bug that costs someone a lineup rather than merely looking untidy — which is why a naive datetime is read as UTC rather than as local, and why a mistyped zone degrades to UTC with a warning rather than raising. `validate_production_config` refuses to boot on an unknown zone name.

### Deployment notes

- **The web service is one gunicorn process with four threads, and sleeps.** `--worker-class gthread --workers 1 --threads 4` in the `Procfile`, Serverless on in the service settings. It sleeps after ten minutes without outbound traffic; the first request after a sleep pays a cold start, and Railway documents that it may answer 502. Anything sending outbound traffic while idle keeps it awake, an uptime monitor included. The price of one threaded process is that module-level mutable state needs a lock — the rate limiter already had one.
- **Migrations run as a Railway pre-deploy command** (`flask db upgrade`), not from application startup. Startup migration races across gunicorn processes, and under Serverless the application boots on every wake.
- **Healthcheck path is `/health`**, set in the service settings. Without it a deploy that boots but cannot reach Postgres reports "online".
- **Cloudflare SSL/TLS must be Full (strict).** Flexible sends plaintext to Railway, so `SESSION_COOKIE_SECURE` cookies never return and login silently fails to persist.
- **The Railway-generated `*.up.railway.app` domain is deleted** once the custom domain works. `CF-Connecting-IP` is only trustworthy for traffic that passed through Cloudflare.
- **`DATABASE_PUBLIC_URL` requires enabling the TCP proxy.** `DATABASE_URL` (private) stays as the application's variable.
- **Railway can silently disconnect from GitHub.** If a push does not deploy, check Settings → Source before debugging anything else.
- Production refuses to boot on a default `SECRET_KEY`, an unset `DATABASE_URL`, a non-https `APP_BASE_URL`, or an unknown `DISPLAY_TIMEZONE`.

### The worker service

A second Railway service from the same repo, run as a **cron job**: start command `python -m worker.tick`, schedule `*/5 * * * *`. Each run does whatever is due — the poll, the calendar sync if its interval has passed, pruning, the hourly heartbeat — and exits. The poll goes first because it is the time-sensitive one, and each job is isolated so a failure in one does not stop the others.

- **No in-memory state.** Every decision about what is due comes from the stored schedule or from `WorkerRun`. Anything a future job needs to remember between runs is stored or derived; a module-level dict in `worker/` is a bug.
- **Overlap is the platform's problem.** Railway skips a scheduled run while the previous one is active, which replaced the one-replica rule a long-running APScheduler process needed and could not enforce. The cost is that a hung run would silently stop all polling, so every run has a hard ceiling of 240 seconds — `SIGALRM`, then `os._exit`, because an exception raised from a signal handler could be swallowed by a job's own `except`. A killed run leaves an unfinished `WorkerRun` row, which is the crash evidence §5 keeps. The health page tells the two apart by age — an open row younger than the ceiling is running, an older one is killed — and counts kills only within the retention window, since pruning keeps the rows forever. The ceiling lives in `app/models/worker.py` so the page can read it without importing the worker.
- **Restart policy: Never.** Exit codes are honest — 1 when a job raised or the ceiling fired — and the default on-failure policy would rerun a failure immediately, spending quota on it again during the one weekend that matters. Job failures are also recorded on their `WorkerRun` row; the cron run list is where the exit code shows.
- **The cron interval and `POLL_INTERVAL_SECONDS` must agree** (§6).
- **No healthcheck path, no pre-deploy command, Serverless off.** It serves no HTTP, `flask db upgrade` stays on the web service, and a cron service is already absent between runs.
- **`FANTASY_NOW` is ignored** and logs a warning on every run if set. A stale value would send the worker chasing a weekend from last December.

**`railway.toml` is deleted.** Railway deprecated Config as Code with a 1 December 2026 cutoff — seventeen days before Jeddah. It had already caused one failure: both services resolve the same root config file, so the worker inherited the web service's `healthcheckPath` and was killed for failing a check on a process that serves no HTTP. The cron schedule and restart policy are dashboard settings for the same reason.

**Region: `europe-west4`.** A Postgres volume cannot be relocated, so moving regions means a new instance and a `pg_dump` restore.

### Divergences from the F1 implementation

| Change | Reason |
|---|---|
| Drop `User.is_contributor` | F1-specific |
| Add `User.last_seen_at` | With remember-me sessions a user can be active daily for months without a login event |
| `League.created_by_id` nullable, `ondelete="SET NULL"`; `role` on `LeagueMembership` | In the F1 app the FK is `RESTRICT` and `NOT NULL`, so any user who has created a league gets an unhandled `IntegrityError` on account deletion. **Live bug in the F1 app, worth patching there too.** |
| Add rate limiting to `/register` | The F1 app leaves public registration open |
| **Client IP from `CF-Connecting-IP`** | Railway's edge rebuilds `X-Forwarded-For` from its own peer, so the client never appears in it. No `ProxyFix` hop count can recover it. Before the fix every visitor shared one bucket. |
| **`session_protection = "basic"`** | `"strong"` pins a session to `request.remote_addr`, which here is a rotating Cloudflare edge address. Also wrong for a mobile-first app: a phone moving between wifi and mobile data changes IP mid-session. |
| Split `config.py` | Environment only; point values in `app/scoring/rules.py`, design tokens in CSS |
| SQLAlchemy 2.x `select()` throughout | The F1 app passes a Flask-SQLAlchemy `Query` into `session.execute()`, which is deprecated |
| Dev dependencies split | pytest and responses were otherwise shipping into the production image |

**Known limitation, accepted:** login rate limiting is in-memory. There is one web process, so one store, but it is lost on every sleep: a block survives only while the service stays awake, so an attacker who pauses for ten minutes gets a clean slate. Acceptable for an invite-scale app; the replacement is a `login_attempts` table, not a bigger dict.

**Known limitation, accepted:** the test suite creates and drops the full schema per test, costing roughly six minutes on the Pi. That is approaching the point where it discourages running the tests before committing, which is the real cost. Revisit with a session-scoped schema and per-test rollback.

---

## 8. Roadmap

**Season 12 (2025-26) is complete and fully ingested locally** — 17 rounds of real data, 510 round scores. The entire scoring engine and every visualisation has been validated against a finished season. Biggest de-risking asset available.

### Phases 0–6 — complete

| Phase | Contents |
|---|---|
| **0 — Foundations** | App factory, config, `/health`, Alembic baseline, auth blueprint, pytest, Railway, Cloudflare, Resend |
| **1 — Data layer** | Provider client, ingestion models, season sync, results ingestion, S12 backfilled |
| **2 — Scoring engine** | `app/scoring/engine.py` and `lineups.py` as pure functions; `sim/` run against all 17 S12 rounds. **No point values changed**; ruleset promoted to `v1` |
| **3 — UI foundations** | Typeface, tokens, primitives, palette, the lineup component, meeting navigation, profiles. Bracket deferred with its risk recorded |
| **4 — Lineup & transfers** | Game schema, lineup service, the editor, the front page. `base.css` deleted |
| **5 — Scoring in production** | `RoundScore`, `PickScore`, `WorkerRun`, the scoring pass, stored-score reads, the poller, `/admin/health` |
| **6 — Leagues & social** | Visibility layer, global league, league lifecycle, standings with movement, friend profiles |

### Phase 7 — Visualisation, complete

| # | Stage | Contents |
|---|---|---|
| 7.1 | The split | `scoring_bridge` → `bridge`, `display`, `queries`, `view` behind a shim; `app/localtime.py` and the timezone filters; `_lineup.html` cleaned of three duplicate macros |
| 7.2 | The weekend view | `app/meetings/routes.py`, `/weekend`, nav and results partials promoted out of the styleguide, the front page linked into it |
| 7.3 | Fantasy points only | FP in the classification, `TP` → `FP` in the profile, the fastest-lap star wired to the engine's own derivation |
| 7.4 | The bracket | `app/meetings/bracket.py` and `_bracket.html`; Phase 3's open risk closed by demonstration |
| 7.5 | Perfect Five, marking, profiles | Personal marking on both tables, the Perfect Five route, the friend profile's arrow nav and info mark, season history |
| 7.5b–d | Corrections | Perfect Five redefined as best picks; the bracket mark fixed; the scored views standardised; one shared `results_context` |
| 7.6 | Trim | The shim deleted with a test asserting it stays deleted; the styleguide reduced to the pages with no production equivalent; profiles answer before the season has scored; the picker gains an info mark |

**Four stages of corrections after 7.5 is worth recording rather than tidying away.** Every one came from using the app rather than from a test: the Perfect Five being unparseable, the bracket's mark having nothing to be tall against, the friend profile not matching the weekend view, and four separate controls asking a cost diff a question about saving. §11 is longer than any previous phase's for the same reason.

**No migration.** See §5.

### Milestones

| Date | Milestone |
|---|---|
| Aug 2026 | Phases 0–2 complete; S12 backfilled |
| Aug 2026 | Phases 3, 4, 5 complete; worker live in production |
| Aug 2026 | Phase 6 complete: leagues, invites, standings, friend profiles |
| **23 Aug 2026** | **Phase 7 complete: the meeting view, the bracket, the Perfect Five, season history** |
| **25 Aug 2026** | **Phase 8 complete: the visual layer, the identity, the static pages** |
| 21 Sep 2026 | Worker moved to cron; web service one threaded process with Serverless |
| Sep–Nov 2026 | Phase 9 — production readiness. Gated on the calendar, so mostly waiting attentively |
| ~Oct 2026 | S13 calendar published; the worker picks it up unattended; S12 loaded to production afterwards |
| Early Dec 2026 | Friends registered, leagues created, opening lineups set during grace |
| **18–19 Dec 2026** | **Jeddah — first live round** |
| Late Dec 2026 | Re-tune places gained/lost against the first real Unleashed race; confirm what an unpublished session actually returns (§6) |

**Phase 7 was planned for early December and landed in August.** Every phase since 3 has run ahead, and the whole roadmap is now roughly three and a half months early against a fixed date. That surplus is not an invitation to add features: the game is complete, and the risk between here and Jeddah is entirely operational — a calendar that arrives in a shape nobody has seen, a session status nobody has observed, and a first weekend that has to work on a phone in front of an audience.

So the surplus went into the visual layer, which needed no calendar and no data, and Phase 9 is production readiness — mostly waiting attentively.

### Phase 8 — Visual refinement, complete

**Not what this document said Phase 8 was.** Production readiness is gated on a Season 13 calendar the provider had not published, so none of its entry conditions could be met. Visual work needed no calendar. It took the gap; production readiness is Phase 9 below, unchanged apart from its number.

The brief was four complaints and one absence. Sections did not separate. `/leagues/<id>` was overwhelming. Shaded backgrounds were the obvious tool and the obvious trap. The mark family was two near-misses rather than a set. And there were no static pages at all, with friends registering in December knowing one sentence about scoring.

| # | Stage | Contents |
|---|---|---|
| 8.1 | Foundation | The surface tier, semantic region spacing, motion tokens, `.panel` as the grouping primitive, full-ink heavy rules retired |
| 8.2 | Identity | Wordmark, favicon, the mark family's rule, the two-row shell, the footer, the pages blueprint |
| 8.3 | Dense screens | Bracket sections as opening panels, duel pairing by inversion, the results section always visible, the subject card |
| 8.4 | Leagues | The table/settings split, standings on the league list, one figure formatter |
| 8.5 | Static pages | How to play from the ruleset; about, privacy, terms |
| 8.6 | Sweep | Error pages, the dead `results=open` contract, dead CSS, `.c-driver` renamed |
| 8.7 | Close | This document |

**No migration, and no Python beyond four small additions**: the pages blueprint, the card route, `view.subject_meeting_score`, and the leagues split. Everything else is CSS and templates.

**Two things were built twice.** Duel pairing was first attempted with space alone and did not read, because a bracket row is two lines tall and the gap between pairs never looked bigger than the gap inside one; the second attempt inverted the ground and needed no space at all. And the nav's live figures were designed, mocked, and dropped before shipping. Both are recorded because the discarded version was the reasonable-sounding one.

### Phase 9 — Production readiness

Entry conditions, in the order they unblock:

- **The S13 sync is the first unrehearsed thing that will happen.** The worker asks for 2027 daily and picks it up alone; nobody has to watch. But the *result* wants inspecting the day it lands: 21 rounds across 13 meetings, eight double-headers, `Round.format` derived for the first time in anger, a shakedown session of unknown type, and deadlines computed from a calendar that has never been parsed. Check `/admin/health` for sync conflicts, then read the derived meetings against the published calendar by eye.
- **Then load Season 12 into production**, in that order. `current_season()` is the latest by year, so S12 arriving first would make the whole app show a finished season as live. After S13 exists it is inert data, reachable only through season history in a profile — which is the entire point of loading it.
- **§10's outstanding admin items.** Mutating actions, idempotent and logged with actor and timestamp; and pushing a deadline later before it passes. A passed deadline is never unlocked through the interface.
- **The S13 qualifying sanity check** (§6) needs a replacement expectation once a real payload exists.
- **DB-backed tests for what Phase 7 shipped.** The phase closes with pure-function coverage — the bracket against the engine, the split's module boundaries, the localtime filter — and three defects that a route test would have caught: the `mark_best` id collision, the Perfect Five's non-determinism across requests, and the friend profile's results fragment respecting visibility.
- **The suite takes about six minutes on the Pi** and §7 records why. That is the point at which it stops being run before committing, and Phase 7 shipped several defects that a run would not have caught but a *habit* of running might have. Session-scoped schema, per-test rollback.
- **A phone, on the day.** Everything since Phase 3 was designed at 360px and checked in device emulation. Jeddah is the first time it is read on a real handset by someone who did not build it — and for most of them the first tap will be a cold start (§7).

### Explicitly not in Phase 9

The game is done. No new scoring rules, no new views, no second season's features. The one thing that will change after Jeddah is the places gained/lost magnitudes, and ruleset versioning exists so that re-tune does not rewrite December.

---

## 9. The S12 simulation

Run against Season 12 in Phase 2b. **No point values changed; ruleset promoted to `v1`.**

- **Places gained/lost is load-bearing**, firing on 55.6% of driver-rounds, near-symmetrically. Cap 4 sits on the knee of the returns curve; a 3-place step scores better on spread but breaks merit ordering (P20 to P11 would outscore a podium).
- **The depth is entirely in transfer timing.** The best fixed lineup for the season and the obvious one are the same lineup, so there is no clever set-and-forget pick. Transfers are worth +100 over a season against a theoretical ceiling of +242.5.
- **The team slot is the low-variance pick.** Its mean equals the driver mean by construction, but its spread is ~30% lower — sd 3.35 against 4.79. Picking a team is the conservative move; that is a feature.
- Race took 61.4% of points distributed; season driver totals ran 104 down to 8.
- The dream team ties on 6 of 17 rounds, worst case 18 lineups out of 20,160.

**That last figure is why the Perfect Five was redefined in Phase 7** (§4.5). It was recorded here as a measurement of the scoring gradient, which it still is — and `dream_team` and `valid_lineups` remain in `app/scoring/lineups.py` so `sim/` can keep asking. It is simply not a thing to put on a page.

**Caveat that must not be forgotten: S12 contains no sprint races.** Season 13's Race 1 is a 30-minute high-downforce sprint with no Pit Boost, which will produce a different overtaking distribution and therefore different places-gained magnitudes. The simulation validates the *mechanic* and gives a defensible starting point; it cannot give correct magnitudes for Unleashed races. Plan an explicit re-tune after Jeddah, and rely on ruleset versioning so the re-tune does not rewrite history.

---

## 10. Open decisions

- **Places gained/lost cap and step:** ships at ±4 in steps of 5 places; confirm or adjust after Jeddah.
- **Team score rounding:** halves permitted. Revisit only if league tables look untidy in practice.
- **Admin surface, still outstanding:** mutating actions (idempotent, logged with actor and timestamp), and pushing a deadline later before it passes. Every remedy `/admin/health` points at is currently a CLI command — a button that rescores a season is the kind of thing that gets pressed by accident on a race weekend.
- **Meeting display name overrides:** `grouping_locked` currently guards both regrouping and renaming, so correcting "Monte Carlo" to "Monaco" also freezes the grouping. Worth splitting if it becomes annoying.
- **S13 qualifying points sanity check:** what the replacement expectation should be, once a real S13 payload exists.
- **Serverless on race weekends:** whether to switch it off from Friday to Sunday, so the weekend's busiest hours never meet a cold start. It is a manual toggle, which is the argument against. Decide after Jeddah from what the cold start actually looks like on a phone.
- **Season 12 in production:** not loaded. Do it *after* the S13 sync (§8).
- **`prof.info_link` has no callers** since the styleguide picker it was written for was deleted. Either the editor's hand-written link folds back into it — with `hx-select` and `hx-push-url` parameters — or the macro goes.
- **The desktop relaxation has never been designed.** `--measure` widens to 46rem above 48rem and everything else is unchanged. That is defensible as "a wide tablet" (§1) and has never been looked at properly.
- **The subject card has no no-JavaScript equivalent.** Its link keeps a working `href`, but that href goes to the season sheet as it did before, so the two paths differ. Parity wants a `?card=` parameter resolved on three pages, which is route work for a path nobody in the current audience takes.
- **The styleguide's standings section renders championship points**, which §3 says are rendered nowhere. It is debug-only and cannot reach production, but it is the one screen contradicting the one-unit rule. Fix or delete.
- **Backup and log retention in `/privacy` are approximations** — "of the order of a week", "roughly a month" — pending confirmation of what Railway actually keeps.
- **A minimum age of 16 is stated** in privacy and terms. It sidesteps UK GDPR Article 8 rather than engaging with the ICO's Children's Code, which is proportionate for a free non-commercial game and is not the same as compliance if this grows.

### Resolved

| Decision | Outcome |
|---|---|
| **Worker runtime** | **A Railway cron job every five minutes.** No scheduler library, no in-memory state, restart policy Never, a 240-second ceiling per run |
| **Web process** | One gunicorn process with four threads, Serverless on |
| Worker restart visibility | Gone with the restarts. The heartbeat reads `WorkerRun` |
| **Surfaces** | **Three grounds and four constraints (§1).** A fill replaces a rule rather than joining one; no recessed surface nests; a surface holds a heading and a list; full-measure and square. `--rule-heavy` survives once, on the appbar |
| **The mark family** | Circle is an action, square is a state. Two sizes, `currentColor`, glyphs from the display face. The star is a documented exemption; a cog was refused |
| **Motion** | Four applications and no fifth, confirming a change the reader caused. Exit is always instant |
| **Identity** | A two-face wordmark preceded by the two stripes in ink. One asset in the project: a favicon drawn as rectangles, because F and E are rectilinear and a home screen cannot be set in type |
| **Navigation** | Two rows, three destinations, the footer carrying everything else. Labels only — a per-tab figure could not be written for Leagues |
| **The league pages** | Table and settings, split. Settings is every member's, not only an admin's |
| **The subject card** | A results row opens the weekend, not the season. Meeting-scoped, and the same macro over the same object as a lineup slot |
| **The rules page** | Rendered from `rules.py`, never typed. The one correct use of `get_ruleset()` with no argument |
| **Static page voice** | A rules page states rules. Rationale lives in this document |
| **Perfect Five** | **The four best-scoring drivers and the best-scoring team, not the best valid lineup.** Ordered by total, then best finishing position, then id, so ties cannot reach the page. The achievability benchmark is given up deliberately |
| **The unit** | **Fantasy points only.** Real championship points are ingested for §6's check and rendered nowhere |
| **The qualifying bracket** | Stages read down the page, per-stage FP, elimination in ink, deltas below the leader. No new primitive — Phase 3's risk closed by demonstration |
| **The scored view** | One shape across three pages: nav bar, verdict, lineup. The verdict's label is the only variable |
| **Navigation** | Arrows where a reader can move; the same bar with spacers where they cannot |
| **Personal marking** | Six drivers — four picks plus both cars of the team pick — belonging to the lineup rendered directly above them |
| **The bridge split** | Four modules, not three: `bridge`, `display`, `queries`, `view`. The shim is deleted and a test asserts it stays deleted |
| **Display timezone** | One config value for the installation, `Europe/London`, rendered through a Jinja filter with `%Z` |
| **Season history** | S12 onward, fantasy points, excluding the season on screen. One `GROUP BY` over `RoundScore`; no migration, no provider call |
| **Two problem levels** | `error` blocks the commit; `caution` is unsaved work and blocks nothing. A second non-team chroma, outside the team clamp |
| **Grace and cost** | Nothing that presents a cost appears during grace: no "In" tags, no transfer figure, and the control says *Save lineup* |
| **Two diffs** | `diff` answers cost, `unsaved` answers pending. Anything a player can act on reads `unsaved` |
| **The styleguide** | Trimmed to tokens, type and palette. Every screen it duplicated is now production |
| Late joiners | Membership is a view over scores, so joining a league late costs nothing. A shared range control (`?last=3` / `?last=5`) handles a new account mid-season |
| Public/global table | One league carrying `is_global`, everyone enrolled at registration, with a per-member opt-out |
| Visibility enforcement | Two predicates in `app/leagues/visibility.py`; no function returns a foreign lineup without a viewer argument |
| Hiding | A flag on the membership row, not a deleted row. Asymmetric |
| Member cap | A config constant, not a column. Does not apply to the global league |
| Invite revocation | Code rotation. No separate closed state |
| Standings shape | One `GROUP BY` over `PickScore` joined to membership, pivoted in Python |
| Standings ties | Shared position, ordered by username. No countback |
| Friend profile scope | Locked weekends, points, transfer cost, one weekend scored. Never the current transfer bank |
| Not-visible responses | 404, never 403 |
| Score storage | Two tables — `RoundScore` user-independent and carrying the breakdown, `PickScore` a per-user projection |
| Partial scoring | Score what has landed, mark the round provisional, say so on the page |
| Rescoring | Delete-and-rewrite per round in one transaction, gated on `scored_at` |
| Scoring location | A separate pass, not inside the ingest. `app/scoring/` may not import SQLAlchemy |
| Live status checks | Skipped. Speculative fetch costs one call where checking first costs five |
| API ceiling | Monthly, summed from `WorkerRun`, checked before any job that would spend a call |
| Worker clock | Real UTC. `FANTASY_NOW` is ignored and warned about |
| Railway config | Dashboard, not `railway.toml` |
| S13 season UUID | Resolved by ending year at run time. The daily sync picks it up on its own |
| Season-start grace | Unlimited free edits until the first deadline of the season |
| Long-term driver absence | Costs a normal transfer; no free move |
| Grid size | 20 drivers, 10 teams — verified, but never hard-coded |
| Transfer cost | Count of changed slots; forced team relocation costs 2, spent atomically |
| Places gained/lost | Ships in v1 — the only midfield resolver |
| Fastest lap source | Minimum `lap_time`, never `fastestLap.rank`. One derivation, so the star and the score cannot disagree |
| Pole source | Qual Final winner, never `gridPosition` |
| Design ground | Light |
| Design tokens | CSS custom properties, not Python config |
| Roster truth | Derived from API data; no curated entry list |
| Deadline | Stored on Meeting with session provenance, monotonic once published |
| Sync conflicts | Safe changes apply silently; unsafe ones skip that meeting atomically and raise a flag |
| Ingested stages | Qualifying and race only |
| Round numbering | Position in the season calendar; immutable once assigned |
| Round format gating | Unleashed rule applies from S13 only |
| Snapshot storage | Sparse — a row only where a player committed |
| Editable weekend | Only the earliest unlocked one |
| Cost baseline | The last snapshot from an earlier meeting, never the row being rewritten |
| Late joiner's bank | Starts at one; grace already gave unlimited edits |
| Grace anchor | `User.created_at`, not league membership |
| Clock override | `FANTASY_NOW`, excluded under test, warns on every use, not gated on `app.debug` |
| Scoring ruleset | **v1** — S12 simulation confirmed the provisional values unchanged |

---

## 11. Working practices

### Process

- **Plan first.** Decisions settled collaboratively before code; mockups before implementation on design-heavy work.
- **Phased, incremental delivery** with testable checkpoints. Resist scope creep.
- **Commit style:** concise imperative, one or two sentences.
- **No emojis.** Country flags are fine.
- **Never migrate on race weekends.** S13 runs 18 Dec 2026 – 25 Jul 2027 across 13 meetings. Worker and scoring changes prefer the gaps; config and template changes are safe anytime.
- This document lives at `docs/SPEC.md` and is the single source of truth. Re-upload to the Claude project whenever it changes materially.

### Delivery

- **Tarballs for new or wholly-rewritten files; anchored snippets for anything else.**
- **An anchor is a unique string, not a section name.** A Phase 8 instruction said "replace the `@layer components {` under the QUALIFYING BRACKET banner", and that string occurs sixteen times in `primitives.css`. The replacement landed in the first block instead — the foundations — and silently deleted every team-stripe rule, the figure and label treatments and the base personal mark. An anchor must be a line that appears once. Where a block runs past about forty lines, ship the whole file instead and reconstruct it mechanically: apply each edit by exact anchor, assert each matched exactly once, and diff the selector set against the live copy before delivering. That is a guarantee no paste instruction can offer.
- **A file that has taken a hand edit is no longer tarball-eligible** until it has been sent back. Phase 7 lost two rounds of editor work this way: `edit.html` was shipped whole from a copy that predated three hand edits, silently reverting them. The rule that prevents it is the same one §5 applies to scores — one source of truth, and the moment there are two they diverge without an error anywhere. Files in that state at the close of Phase 8: `lineups/home.html`, `lineups/edit.html`, `lineups/_lineup.html`, `leagues/index.html`, `leagues/_table.html`, `tokens.css`.
- **Multi-line terminal work:** write to `/tmp` via `cat >` and run with `PYTHONPATH=. python /tmp/script.py` to avoid paste mangling.
- **Quote multi-word `.env` values.** python-dotenv tolerates `NAME=Formula E Fantasy`, but `source .env` reads it as a command invocation and fails obscurely.

### Checks

- **Run `pyflakes` over any route you have edited before committing.** Rendering templates in isolation does not catch a name the view function never defined, and that class of error reaches the browser as a 500 rather than a failing test.
- **pyflakes does not honour `# noqa`** — that is flake8. An import kept for a side effect is silenced by naming it in `__all__`. Delete every other unused import: a check that always prints one line stops being read.
- **Verify a hand-written migration by autogenerating twice.** Alembic silently omits `use_alter` foreign keys, so the first pass can look clean and be wrong.
- **Do not couple a test to a template's wording.** A Phase 0 auth test asserted on the string `Users:` and broke when Phase 5 restyled the admin index. If the claim is authorisation, assert the status code. The same rule applies to a test that greps source: `test_the_compatibility_shim_is_gone` matches `import` statements, not mentions, because ten modules name the deleted shim in their docstrings and that prose is how a reader learns what they used to be part of.
- **Integer inputs:** `type="text"` with `inputmode="numeric"` rather than `type="number"` with `step="1"` — better mobile behaviour.

### Defects worth not repeating

**Two similar questions are not one question — found four times.** The lineup editor measures a draft against two different baselines, and four separate controls read the wrong one:

| Where | Symptom |
|---|---|
| The commit affordance (Phase 6) | A first-ever lineup could never be saved: the diff was empty however much changed |
| The "In" tags (Phase 7) | Every slot accumulated a tag during grace, recording a cost that did not exist |
| The confirmation dialog (Phase 7) | After committing one swap, a second swap's dialog re-listed both |
| The picker's "Put back" list (Phase 7) | Offered to undo a *committed* transfer, which made a new change and enabled the save button |

All four asked "what did this weekend cost" when they meant "is there anything pending". §2 now states the rule as one sentence — anything a player can act on reads `unsaved`; only the cost figure reads `diff` — because the pattern is more useful than any one instance.

**Two id sequences are not one namespace.** `mark_best` tested every pick against `set(best.drivers) | {best.team_id}`, one merged set across two tables with independent primary keys — so at this grid size driver 4 and team 4 are the same integer and any driver colliding with the best team's id was starred wherever he appeared. Intermittent, because it only showed when the collision landed on a pick someone held. Compare within kind. Same class as `LineupPick.driver`/`.team` colliding with the classmethod in Phase 4.

**`hx-boost` on a container is inherited by every descendant**, including `hx-target`, `hx-select` and `hx-push-url`. A child with its own `hx-get` still obeys the parent's selection, so the editor's info mark fetched a profile fragment, tried to `hx-select="#editor"` out of it, found nothing and swapped nothing — a silent no-op with the URL changing anyway. §4.3 chose one boosted region specifically so no fragment template could drift, which is a good decision with this cost. Any link inside it that wants a different target must say `hx-select="unset"` and `hx-push-url="false"` explicitly, and the failure mode is silence rather than an error.

**Layout on the base, colour on the modifier.** `.problem--error` carried the grid, gap and padding as well as the hue, and `.problem__mark` hardcoded `--error` with no modifier of its own. A second level could not be added without either duplicating the layout or inheriting the wrong colour. The mark now takes `currentColor`.

**`:first-of-type` matches on element type, not class.** `.bracket__row:first-of-type` never matched, because the first `div` in a stage is its heading. Adjacency selectors instead.

**A pseudo-element hung off `> :first-child` needs that child to have height.** `.is-yours` works on a `<tr>`, where a cell is as tall as its row, and fails on a grid, where the first child is a baseline-aligned item — one line tall in a group row and *zero* in a duel row, where the cell is empty. Two symptoms, one cause. Hang it off the row.

**Do not name a helper into a framework hook.** WTForms treats `filter_<fieldname>` exactly as it treats `validate_<fieldname>`. A `JoinLeagueForm.filter_code()` written as a method the route would call was found by WTForms and invoked with the field value, so merely constructing the form raised `TypeError` and the page 500ed on a GET before any input existed. **Every form needs a test that renders its page**, not only one that exercises the function behind it.

**The empty state is a real state.** A friend profile for a player with no lineups rendered a list of weekends whose links all produced an identical page, with nothing anywhere saying why. The same principle produced three post-lock states on the weekend view (§4.4) and a profile that answers before the season has scored (§4.2).

**A page-local `<script>` block is a copy waiting to diverge.** The dialog handlers were written inline in the styleguide's meeting page, then wanted by three other screens. They live in `app/static/js/dialogs.js`, loaded by the app shell.

**Interactive fragments keep a working `href` alongside their `hx-get`.** The page functions without JavaScript and HTMX enhances it. Click handlers are delegated from the document rather than bound per element, so swapped-in markup behaves like markup present at load.

**A read written twice is a read that will disagree.** `_player_results` was a copy of `_results_context` differing in one line — which URL the disclosure's links point at. It is now one function with six callers and a `base` argument. The same instinct deleted the styleguide's six duplicated screens: a debug-only surface is where drift goes unobserved longest, and `/styleguide/meeting` had been raising a 500 since Phase 3 because its template was never committed.

**An outdented mark and a clipped ancestor are silently incompatible.** Every "this is yours" treatment in this application is a pseudo-element outdented into a reserved gutter — it sits *outside* its row's box. Phase 8 gave `::details-content` `overflow: clip` so a disclosure would not spill mid-transition, and `clip` clips both axes, so an animation added to the results section removed every personal mark inside it: the classification and the bracket at once. `overflow-clip-margin` hands back exactly the gutter. Worth knowing as a class rather than as an incident — the failure is invisible rather than broken, and nothing anywhere reports it.

**One concept, two vocabularies, and no translation layer.** A URL carries `d9`; a `PickScore.kind` is `"driver"`. Both are right where they live. The subject-card route was written to call `subject_meeting_score(kind="d")`, which matched neither branch and fell through to the one return that produces silence, so every card request in the application answered nothing. Both vocabularies stay; they now meet in one named constant, and that constant is the only place they touch.

**A route where every failure returns the same response cannot be debugged from outside it.** The card fragment answered 204 whether the meeting was missing, the deadline had not passed, the subject was unreadable, or the subject had no scores. 204 is the right *response* — an error document swapped into a dialog host is worse than nothing — but the reason belongs in the log. Any fragment route that answers with silence needs to say why at debug level.

**The class a component defines is the class its markup has to use.** The league range switch rendered its tabs as `.label u-caps` with a `u-semi` on the current one, so none of `.vswitch__tab` — its padding, its underline, its current state — had ever applied. It read as a spacing fault and was reported as one. The fix was not margins.

**One signal, one meaning.** In the standings table weight meant "this row is yours" *and* "this is the column that decides the order", so a viewer's row was bold because it was theirs and every row's points were bold because they were points. Neither could be read. Prominence that is not personal marking has to be carried by ink.

**A derived figure is allowed if a test pins it to the recomputation.** `transfer_cost`, `scoring_provisional` and the bracket's per-stage points are all second copies of something the engine knows. Each has a test asserting equality with the authoritative derivation. That is the price of the shortcut, and it is worth paying.

---

## 12. Repo structure

```
fe-fantasy/
├── app/
│   ├── __init__.py          # application factory
│   ├── config.py            # environment and Flask only
│   ├── clock.py             # now(), and the FANTASY_NOW gate
│   ├── localtime.py         # the display timezone, and its Jinja filters
│   ├── extensions.py
│   ├── cli.py               # set-admin, config-check, sync-season, backfill-results, score-season
│   ├── utils.py             # admin_required, client_ip, touch_last_seen
│   ├── palette.py           # team hue seeds — data repair, no design
│   ├── auth/                # routes, forms, email, rate_limit
│   ├── admin/               # read-mostly; health view, request-info diagnostic
│   ├── leagues/
│   │   ├── visibility.py    # the two predicates; no foreign read bypasses it
│   │   ├── service.py       # create, join, leave, administer, the global league
│   │   ├── invite.py        # the landing, and the invite a visitor carries
│   │   ├── standings.py     # one GROUP BY over PickScore, pivoted
│   │   ├── profile.py       # another player's season
│   │   └── routes.py        # /leagues, /join/<code>, /players/<id>
│   ├── lineups/
│   │   ├── roster.py        # the pickable grid for a round
│   │   ├── draft.py         # what is broken, what it costs, what each option does
│   │   ├── service.py       # open weekend, grace, bank, commit
│   │   └── routes.py        # / and /lineup
│   ├── pages/               # how-to-play, about, privacy, terms. No database
│   ├── meetings/            # scoring in production, and the weekend views
│   │   ├── bridge.py        # ORM rows -> engine dicts, and the ruleset to use
│   │   ├── display.py       # every string a reader sees. Engine only — no ORM, no Flask
│   │   ├── queries.py       # reads returning display-ready shapes
│   │   ├── view.py          # lineup + stored scores -> template view models
│   │   ├── bracket.py       # the qualifying knockout as a view model
│   │   ├── scoring.py       # the scoring pass: completeness, partial, idempotent
│   │   ├── reads.py         # stored scores, shaped like the engine's output
│   │   └── routes.py        # /weekend, /weekend/perfect-five, the card, the fragments
│   ├── models/              # user, league, lineup, score, worker, calendar, grid, result
│   ├── providers/
│   │   ├── base.py          # normalised dataclasses + ResultsProvider protocol
│   │   ├── ocblacktop.py    # the only module that sees a vendor payload
│   │   └── errors.py        # Blocked / Auth / Request / Transient / Payload
│   ├── ingest/              # stages, derive, conflicts, season, results, status, checks
│   ├── scoring/             # rules.py, engine.py, lineups.py — no Flask, no SQLAlchemy
│   ├── styleguide/          # debug-only: tokens, type, palette. Nothing else
│   ├── static/
│   │   ├── favicon.svg      # the only asset in the project. See §1
│   │   ├── css/             # tokens.css, primitives.css, styleguide.css
│   │   ├── fonts/           # Archivo, Anybody, subset woff2 + OFL
│   │   └── js/              # htmx.min.js, dialogs.js — self-hosted, no CDN
│   └── templates/
│       ├── lineups/         # _lineup.html (the component), home, edit
│       ├── meetings/        # weekend, perfect_five, _nav, _results, _results_body,
│       │                    # _bracket, _profile, _profile_sheet
│       ├── leagues/         # index, detail (the table), settings, new, join, landing
│       ├── pages/           # how_to_play, about, privacy, terms
│       ├── players/  auth/  admin/  errors/
│       └── styleguide/      # _shell, index
├── worker/                  # outside app/: the application must not import it
│   ├── tick.py              # the entrypoint: one cron run, everything due, then exit
│   ├── jobs.py              # poll and sync, as plain functions
│   └── runs.py              # WorkerRun recording and the monthly ceiling
├── sim/                     # Phase 2b standalone simulation
├── migrations/versions/     # 0001 baseline .. 0006 global league
├── tests/
├── docs/SPEC.md
├── wsgi.py  requirements.txt  requirements-dev.txt  Procfile  .python-version
└── .env.example  README.md
```

Five deliberate choices:

- **`providers/` exists from the first commit**, per the §6 mitigation. A vendor swap becomes a new module implementing `ResultsProvider`, rather than a refactor of everything that touches results.
- **`scoring/` imports nothing from Flask or SQLAlchemy.** It takes plain result dicts and returns points, which lets the simulation run without a database. A test asserts it.
- **`meetings/display.py` carries the same constraint**, for the same reason at a different level: wording is what changes most often and is hardest to test, so it should be the cheapest thing in the project to import. A test walks its imports statically — importing it at runtime proves nothing, because `app/__init__.py` pulls in the models regardless.
- **`sim/` sits outside `app/`** so there is no route by which the web application can be imported into it.
- **`worker/` sits outside `app/` for the mirror reason**: the worker may import from the application, and the application may not import the worker. That is why the session-window queries the admin health page and the poller both need live in `app/ingest/status.py`.

**On the four meetings modules rather than the three §8 named.** `queries.py` holds `select()` statements and `view.py` brute-forces the grid; a module doing both would be the "does five jobs" problem again at smaller scale. The dependency order is `display` ← `bridge` ← `view`, with `queries` reading `display` — no cycles, and the worker imports `bridge` and nothing else in the set.

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

Treat these strings as **unstable**. Match defensively (normalised, case-insensitive substring), and **fail loudly on an unrecognised qualifying session name** rather than skipping it silently — a silent skip would corrupt scoring without any visible error. Sessions of any other type are recorded as `other` and ignored.

**Duel sessions return only their two participants.** A full bracket therefore requires all nine qualifying sessions to be fetched per round.

### Seasons index — `/seasons`

| Field | Notes |
|---|---|
| `id` | UUID. Required by `/seasons/{id}`; a numeric year returns 400. |
| `year` | **The year the season ENDS.** S12 is `2026`; S13 will be `2027`. |
| `status` | Null for every season observed. Not usable. |
| `roundCount` | Null for every season observed. Not usable. |

Twelve seasons present, 2026 back to 2015. **No 2027 entry as of 23 August 2026.**

### Season detail — `/seasons/{uuid}`

Bare object with four keys: `season`, `drivers` (20), `teams` (10), `schedule` (17).

`schedule[]` entries are events **without `schedule[]` of their own** — no session times. Driver entries carry standings (`position`, `points`) plus `teams[]`, each with `participationRounds`.

### Event object

| Field | Notes |
|---|---|
| `id` | UUID |
| `name` | Sponsor-polluted. Do not parse or group on it. |
| `dateStart` / `dateEnd` | Equal for Formula E — each event is a single day. Plain dates, no time component. |
| `status` | `completed` \| `scheduled` |
| `location` | `{id, name, city, country{...}}` — `location.id` is stable across seasons |
| `schedule[]` | Embedded session array; only present via `/events` |

### Session object (inside `event.schedule[]`)

| Field | Notes |
|---|---|
| `id` | UUID, needed for the results path |
| `name` | The only way to identify a bracket stage |
| `type` | `practice` \| `qualifying` \| `race` \| `other` |
| `startTime` / `endTime` | **Not `dateStart`/`dateEnd` as on the event.** ISO 8601 UTC with millisecond precision |
| `status` | `scheduled` \| `ongoing` \| `completed` |

### Result row

| Field | Notes |
|---|---|
| `id` | UUID of the **result row**, not the driver |
| `position` | **String** (`"1"`) |
| `gridPosition` | **Int** (`5`). **The post-penalty starting slot, not the qualifying result.** Present-and-null in qualifying sessions. Null or zero in a race means no places gained/lost score — log it. |
| `driver` | `{id, firstName, lastName, code, number}` — `code` null for 16 of 20; `id` is the only stable key |
| `team` | `{id, name, shortName, color}` — `color` unreliable |
| `carNumber` | Top-level, alongside `driver.number` |
| `status` | **Absent on qualifying rows.** Null for classified finishers, `"DNF"` for retirements. Retirements still receive ranked positions. |
| `points` | **Absent on qualifying rows.** String decimal elsewhere — real FE championship points. Used only by the §6 sanity check; never displayed. |
| `fastestLap` | `{rank, time, lap}` — **`rank: 1` marks the fastest lap among top-ten finishers, not of the race.** Store it; the fantasy point comes from `lapTime` (§3). |
| `lapTime` / `displayTime` | **Semantics differ by session type.** In a race, `lapTime` is the driver's fastest lap and `displayTime` the total race time. In a qualifying duel, `lapTime` is null and `displayTime` carries the lap time. **`displayTime` shape varies** — never split on `:` expecting a fixed part count. |

**Always null in Formula E payloads** (populated for other series, so don't be misled by the schema): `laps`, `chassis`, `engineManufacturer`, `gap`, `interval`, `pitStops`, `bestLapTime`, `bestLapNumber`, `sectors`, `tireStrategy`, `q1Time`, `q2Time`, `q3Time`.

The absence of `laps` is why **retirement ordering is unavailable**.

### Error shapes

`/seasons/2026` (numeric where a UUID is expected):

```json
{"message": "Validation failed (uuid is expected)", "error": "Bad Request", "statusCode": 400}
```

A Cloudflare 1010 block returns an **HTML** body with HTTP 403, distinguishing it from an API credential rejection, which returns JSON. Sustained request rates return **HTTP 429**.

### Real FE championship points (cross-validation, season-scoped)

**Season 12 and earlier:** `25 / 18 / 15 / 12 / 10 / 8 / 6 / 4 / 2 / 1` for the top ten, plus 3 for pole and 1 for fastest lap (top-ten finishers only). The pole bonus attaches to the **Qual Final winner** and is paid even to a driver who retires — Mortara scored 3.0 from a P18 DNF at Tokyo.

**Season 13 onward:** the race distribution is unchanged, but qualifying now awards championship points on a sliding scale to the eight drivers reaching the Duels. **The S12 check will produce false failures on S13 data.** The implementation is gated on season.

The top ten still defines the "points finish" rule in §3, which is unaffected.

### Fixture inventory

| File | Contains |
|---|---|
| `events_bare.json` | 20 events with `meta` pagination block; mixed completed/scheduled |
| `events_limit.json` | 50 events — demonstrates `?limit=` working |
| `events_page2.json` | Page 2 — for the client's page-walk test |
| `events_param_season.json` | `?season=` — byte-identical to `events_bare.json` |
| `events_param_seasonid.json` | `?seasonId=` — same |
| `events_param_perpage.json` | `?perPage=` — same |
| `seasons_list.json` | 12 seasons, year → UUID; no 2027 |
| `season_detail.json` | S12, re-fetched after the London finale |
| `season_numeric_400.json` | The 400 "uuid is expected" error shape |
| `results_race.json` | Tokyo R2 race — 20 rows, 4 DNFs, 16 null `driver.code`, over-hour `displayTime` |
| `results_qual_final.json` | 2 rows — duel session shape; `points` and `status` keys absent |
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
