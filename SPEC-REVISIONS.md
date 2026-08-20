# SPEC.md revisions — Phase 3 design language

Apply these as replacements. Each block says exactly where it goes.

---

## 1. Add to the revision notes, after revision note 3

> **Revision note 4 (19 August 2026).** Phase 3 design language settled.
> Typeface, type scale, colour system and layout primitives fixed (§1);
> **the lineup component is now an architectural commitment, not a screen** —
> one component in three states, described in the new §4.1. Team colour ships
> as two hue-seeded stripes with a hue-aware lightness clamp (§1, §7). A single
> non-team colour is admitted for broken-rule states only (§1). The transfer
> flow's handling of the forced team relocation is specified (§2, §4.1): the
> draft is allowed to sit invalid, and commit is disabled until it resolves.

---

## 2. Replace the "Design values" subsection of §1 entirely

### Design values

The real goal of this project is learning UI, UX, and the clear, beautiful
presentation of dense structured data.

- Minimal, clean, engaging — but clarity beats minimalism when data is dense
- Genuinely unique; must not read as generically generated
- **Avoid "AI-flag" patterns:** hero graphics, pill-shaped tags, gradient
  shading, decorative iconography
- Typography and layout do the work that colour and decoration would otherwise
  do
- No reuse of the F1 app's parchment/moss language — clean-sheet visual exercise
- This explicitly retires the pill component used throughout the F1 app

**Ground: light.** Deliberately contrary to Formula E's own very dark brand
identity, and contrary to the default look of a motorsport data app. A light
ground also makes the negative values in places-lost scoring easy to render
legibly without an alarm-red fill.

#### Typography — settled

**Archivo** (SIL Open Font License, variable, weight 100–900, width 62–125) for
all text and data. **Anybody** (SIL OFL, variable) for display only. Both
self-hosted as subset woff2 with the variable axes preserved; no font CDN.
Subset to Latin plus Latin Extended-A and B, because the data contains `Martí`,
`Müller`, `CITROËN` and `São Paulo`.

**Anybody's scope is fixed and narrow:** round numbers, meeting mastheads, and
a pick or lineup total. Nothing else, never below `--step-5`, never inside a
table cell. Its settings are width 100, weight 700. Personality used everywhere
stops being personality; if Anybody is wanted somewhere outside that list, the
hierarchy is failing and should be solved with Archivo's weight and width axes
instead.

**The width axis is load-bearing.** The longest constructor name on the grid is
thirty characters, and `--width-condensed` at 62% holds it on one line at
`--step-2` on a 360px viewport. That is why no column in this app truncates,
uses an ellipsis, or needs a tooltip.

No monospace face anywhere. Lap times are Archivo condensed with
`font-variant-numeric: tabular-nums`; monospace numerals in a points table read
as code rather than as scores, and dropping the face saves a file.

#### Scale

Seven type steps, in `rem`, so a raised phone text size enlarges the app rather
than being ignored. The data size is `--step-3` (13px equivalent); `--step-1`
(11px) is permitted for tracked uppercase labels only.

**Form inputs are pinned at 16px** in the base layer. Below that, iOS Safari
zooms the viewport when an input takes focus, and every layout decision here
stops being true.

Spacing is a nine-step 4px grid, also in `rem`.

#### Colour

**Team hue is the only chroma on the page**, with one exception below.

Each team is two stripes. The provider's `team.color` supplies **hue only**;
lightness and chroma come from `tokens.css`. Stripes are rules — never fills,
never dots — because a rule aligns with the row it belongs to and reads at 3px
where a dot needs 8px and becomes decoration.

**The clamp has two tiers, routed by hue.** Yellows through cyans (hue 60–250)
cannot hold the standard chroma at the standard lightness — at hue 100 the sRGB
gamut tops out near 0.118, so a yellow seed clamped to lightness 0.56 renders as
olive brown. Those hues take a lighter tier. Perceptual weight is not lightness
alone: a saturated yellow at 0.72 and a red at 0.56 read as equally present,
whereas forcing both to one number makes one of them mud.

The second stripe is an independent channel with four treatments: a declared
secondary hue, a derived tint of the primary, achromatic dark, or achromatic
light. Hue and treatment together give roughly forty distinguishable
combinations from ten hues, which is what allows four red brands to coexist.

Achromatic seeds exist because black has no hue. **When brand and legibility
disagree, the stripe answers "which team", not "what does the car look like".**

**Colour never carries meaning alone.** Ten hues exceed what anyone reliably
distinguishes at a glance, so the stripe is a recognition aid and the team name
is always present.

**No accent colour.** Personal marking — "this is yours", and selection in the
picker — is structural: full ink, a heavier weight, and a rule in a reserved
gutter. One visual language for "yours", and it is not colour. An accent hue
would have ten team hues to compete with and would either lose or shout.

**One exception: `--error`, for a broken rule only.** Deliberately placed
outside the team clamp — darker and more saturated than any stripe can be —
because three teams on this grid are red and an error must never be mistakable
for an identity. Used as text and as a heavy rule; never as a stripe. Its
accompanying mark is a glyph from Anybody inside a ruled square, not an icon
asset.

#### Tokens

**Design tokens live in CSS, not Python.** Colour, spacing and type scale are
custom properties in `static/css/tokens.css`. The F1 app's approach — a
`PALETTE` dict in `config.py` injected into Jinja — makes every colour tweak a
Python edit and a redeploy, and blocks `color-mix()`, `light-dark()`, and
relative colour syntax. Do not repeat it.

Two tiers only. Primitives (`--ink-600`, `--step-3`, `--space-4`) are named for
what they are; semantics (`--text-mid`, `--rule`, `--surface`) for what they do.
Components read semantics and never primitives. A component wanting a value
with no semantic name means the value is missing a name.

Cascade layers are declared once, at the top of `tokens.css`: `reset, tokens,
base, layout, components, utilities`. Later layers win regardless of selector
specificity. Anything outside a layer beats everything inside one, so unlayered
CSS is the escape hatch and stays empty.

**`app/palette.py` is the one Python exception, and it holds no design.** It
maps a team to a hue seed and repairs seeds the provider cannot supply — `000000`
has no hue, so without it Jaguar and Andretti would both resolve to hue 0 and
paint themselves red. That is data repair. The numbers deciding how the palette
*looks* are in CSS.

**Light only for v1.** Adding a dark mode to a well-structured token file is
cheap later; dual-mode doubles the design work in the phase where the point is
learning.

---

## 3. Add as a new §4.1, immediately after the §4 view list

### 4.1 The lineup component

**One component, three states.** This is an architectural commitment, not a
visual preference: the lineup is the shape a player learns once, and it is the
shape of the whole app.

| State | Slots contain | Tapping a slot |
|---|---|---|
| `empty` | nothing | opens the picker |
| `edit` | current picks | opens the picker to swap that slot |
| `scored` | one total per pick | discloses that pick's breakdown |

Geometry is identical in all three: four driver slots in a 2×2 grid, the team
slot as a wider band beneath. A driver slot is boxed on four sides; the team
slot is ruled top and bottom and open at the sides, so a different class of pick
reads as a different class of object with no label saying so.

**Slot order never re-sorts by score.** A layout that reshuffles by performance
cannot be read at a glance, which is the only thing this component is for.

**One number per slot.** A double-header adds its rounds together and shows the
sum. The split by round, and within a round by qualifying against race, is
disclosed on tap and never shown on the face of the component. Qualifying and
race are kept apart in the breakdown rather than concatenated: they are separate
contests with different ceilings, 8 against 17, and merging them hides which
half of the weekend went well.

**No colour signifies a double-header.** Colour means team identity and nothing
else. The masthead naming two round numbers is the signifier.

#### Two vessels, chosen by what the user is doing

- **The picker is a task** — it has a start, an end and a result. It is a modal,
  using the native `<dialog>` element for focus trapping, escape-to-close and
  the backdrop, with no library.
- **The breakdown is reading** — the lineup must stay on screen as an anchor,
  and a reader opens two or three in a row to compare. It is inline disclosure
  below the grid, one open at a time.

#### The picker shows the whole roster

Illegal options are **greyed with the reason stated, never hidden**. A
constraint the interface silently enforces is one the player never learns, and
this game has exactly two rules worth learning. Selecting a driver marks their
teammate unavailable; it also marks that constructor unavailable in the team
list.

#### Draft state and the forced relocation

The editor holds a draft and writes one snapshot on commit (§2). Because a
forced team relocation changes two slots atomically, **there is no legal
single-slot intermediate** — so the draft is allowed to sit invalid rather than
being treated as an error to prevent.

While invalid: the offending slots are marked, the reason is stated once above
the component in the interface's own voice ("Too many drivers from CITROËN
RACING — pick one"), and commit is disabled. An incomplete draft is not
invalid; that is a state the slot counter already shows.

**Validation is server-side, always.** The prototype holds its draft in the
query string precisely so the constraint check and the transfer cost come from
`app/scoring/lineups.py` — the same module the server enforces on commit —
rather than from a mirrored copy in JavaScript that can drift. Phase 4 replaces
the full page reload with an HTMX partial and keeps that property.

---

## 4. Add to the §10 Resolved table

| Decision | Outcome |
|---|---|
| Typeface | Archivo for text and data; Anybody for display only, width 100 weight 700, scope fixed in §1 |
| Type scale | Seven steps in `rem`; data at 13px equivalent; form inputs pinned at 16px |
| Colour system | CSS custom properties, two tiers, cascade layers; light only in v1 |
| Team colour | Two hue-seeded stripes, hue-aware lightness clamp, four secondary treatments; `app/palette.py` holds seeds only |
| Accent colour | None. Personal marking is structural. `--error` is the sole non-team chroma and applies to broken rules only |
| Lineup component | One component, three states; 2×2 driver grid with a distinct team band; order never re-sorts |
| Breakdown | Disclosed on tap, split by round then qualifying against race; never shown by default |
| Picker vessel | Native `<dialog>`; whole roster shown with illegal options greyed and reasons stated |
| Invalid drafts | Permitted and legible. Slots marked, reason stated once, commit disabled |

---

## 5. Amend §12, repo structure

Add under `app/`:

```
│   ├── palette.py           # team hue seeds — data repair, no design
│   ├── styleguide/          # debug-only; tokens, lineup states, results
```

Under `app/static/css/`, replace the `base.css now; tokens.css and the system
in Phase 3` comment with:

```
│   └── static/css/          # tokens.css, primitives.css — the design system
```

---

## 6. Correction to `app/scoring/rules.py`

Not a spec change, but it contradicts §3. The comment in `RaceRules` still
instructs deriving fastest lap from `fastestLap.rank`, which the 19 August
correction reversed. `engine.py` does it correctly; only the comment is wrong,
and it is the first thing a future reader consults.

```python
    # Fastest lap is UNCONDITIONAL here. Formula E awards its championship
    # fastest-lap point only to a top-ten finisher; this game does not apply
    # that condition. Derive from the minimum `lap_time` across the race
    # classification, never from `fastestLap.rank` — that field is restricted
    # to championship-eligible drivers and disagrees with the truth on eight
    # of seventeen Season 12 rounds.
```
