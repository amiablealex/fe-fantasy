# Phase 3, step 1 — type specimen

Nothing here ships to production. The blueprint registers only when
`app.debug` is true, and the whole surface is deleted or rewritten once the
typeface is settled.

## What is in the tarball

```
app/styleguide/__init__.py          debug-only blueprint, /styleguide
app/styleguide/data.py              real S12 content, hardcoded
app/templates/styleguide/specimen.html
app/static/css/specimen.css         disposable, NOT tokens.css
app/static/fonts/Archivo.woff2      variable, wght 100–900, wdth 62–125
app/static/fonts/Anybody.woff2      variable, wght 100–900, wdth 50–150
app/static/fonts/Newsreader.woff2   variable, wght 200–800, opsz 6–72
app/static/fonts/OFL-*.txt          licences, required by the OFL
```

All three faces are subset to Latin + Latin Extended-A + Extended-B, currency,
arrows, and the true minus sign U+2212, with the variable axes preserved and
the `tnum` / `lnum` / `zero` / `case` features kept. Archivo is 136 KB, Anybody
68 KB, Newsreader 124 KB.

## 1. Extract

From `~/projects/fe-fantasy`:

```bash
cd ~/projects/fe-fantasy
git checkout -b phase3-typeface
tar xzf ~/fe-phase3-step1.tar.gz
git status
```

`git status` should show only additions under `app/styleguide/`,
`app/templates/styleguide/`, `app/static/css/specimen.css`, and
`app/static/fonts/`. Nothing existing is touched.

## 2. Register the blueprint

In `app/__init__.py`, alongside the other `register_blueprint` calls, add:

```python
    if app.debug:
        from app.styleguide import bp as styleguide_bp
        app.register_blueprint(styleguide_bp)
```

The import sits inside the guard on purpose, so the module is never even
loaded in production.

## 3. Run it, bound to the network

```bash
cd ~/projects/fe-fantasy
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

`--host=0.0.0.0` is what makes it reachable from your phone. Debug mode on a
LAN-exposed port gives anyone on your network a Python console via the
debugger, so stop the server when you are done rather than leaving it up.

Find the Pi's address if you do not know it:

```bash
hostname -I | awk '{print $1}'
```

## 4. Open it on the phone

On the desktop: `http://localhost:5000/styleguide`

On the phone, same wifi: `http://<pi-ip>:5000/styleguide`

The phone is the one that counts. Desktop devtools emulation gets text
rendering wrong — different rasteriser, different subpixel handling, different
effective DPI — and text rendering is the entire question here.

## 5. What to judge

Three controls at the top: text face, display face, size. Nine text/display
combinations, three sizes each. Do not try to evaluate all of them.

Work in this order.

**First, the text face at 12px.** Set display to anything, size to 12, and
look only at blocks 02, 03 and 04. Ask:

- Does block 03 hold seventeen rows and six columns without horizontal scroll?
- In block 04, does width 62 hold `LOLA YAMAHA ABT FORMULA E TEAM` on one line?
- In block 05, is the minus in `−4` unmistakably a minus and not a hyphen?
- In block 09, are `Martí`, `Müller` and `CITROËN` clean, or do the accents
  collide with the cap height?

Newsreader will almost certainly lose this on the width test alone — it has no
width axis, so all four rows in block 04 render identically. That is the
intended demonstration.

**Second, the display face in blocks 01, 05 and 06.** This is the real
question and the one I want your judgement on rather than mine. Anybody is the
risk: square-shouldered, instrument-cluster lineage, genuinely of the subject
— or costume. Newsreader is the safe alternative and pushes the whole thing
toward printed results annual. Archivo-as-display is the null hypothesis, one
file, no second face at all.

**Third, size.** 12 against 13 against 15. My expectation is that 13 is the
data size and 12 is reserved for labels, but the phone decides.

## 6. What to tell me

- Text face: which, and what specifically failed for the others
- Display face: which, or "neither, use Archivo throughout"
- Size: does 12 hold, or is 13 the floor
- Anything that looked wrong rather than merely different

Screenshots from the phone are more useful than description.

## 7. Do not push yet

This branch stays local until the typeface is settled. There is nothing in it
that production needs, and merging a specimen that names three candidates when
we are keeping one just puts a deletion commit in the history.

When we have decided, the merge to `main` carries the chosen face only, the
two rejected woff2 files are deleted, and `tokens.css` arrives in the same
commit.
