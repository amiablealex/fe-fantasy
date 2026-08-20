# Phase 3, step 12 — HTMX, state that survives, and figures that add up

```bash
cd ~/projects/fe-fantasy
tar xzf ~/fe-phase3-step12.tar.gz
source .venv/bin/activate
FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

```
new       app/static/js/htmx.min.js               2.x, self-hosted, 52 KB
new       app/static/js/htmx-LICENSE.txt
new       app/templates/styleguide/_results_body.html
replaced  app/styleguide/__init__.py              /styleguide/lineup/results
replaced  app/templates/styleguide/_lineup.html   no section subtotals
replaced  app/templates/styleguide/_nav.html      carries state across meetings
replaced  app/templates/styleguide/_results.html  hx attributes on the switches
replaced  app/templates/styleguide/_shell.html    loads htmx
replaced  app/templates/styleguide/lineup.html    includes the partial
```

## HTMX arrives

This is the case §7 put it in the stack for, so it is worth doing properly
rather than working around.

Switching round or stage now swaps the Results body in place: no reload, no
scroll jump. The route is `/styleguide/lineup/results`, and it renders
`_results_body.html` — **the same template the full page includes**, so the
fragment and the page cannot drift apart.

`hx-push-url` keeps the address bar in step, so the back button works, a reload
lands in the same place, and the section stays open. The links keep their plain
`href` as well, so the whole thing still works with JavaScript off; HTMX
intercepts when it is there. That is the property worth protecting as more of
this arrives in Phase 4.

Self-hosted, like the fonts. No CDN.

## An open Results section survives the arrows

Tapping to the previous meeting with Results open now lands with Results open,
on the same stage. Collapsing it every time punished exactly the reader who was
browsing results.

## The figures add up

Section subtotals are gone. Your reasoning was right and it is worth stating as
a rule: **every small figure on a breakdown adds up to the large one.** With a
subtotal, &minus;2 appeared twice on one screen, which invites the reader to
check the arithmetic and find it apparently wrong.

    Round 9 · E-Prix                     4
    Qualifying
      Eliminated in Group B P10
    Race
      Started P17 · finished P8
      Points finish  P8                  2
      Places gained  9 places            2

A qualifying section that scored nothing now shows no figure at all, which is
correct: it says what happened and claims no points.

## Worth checking

- Results open → switch stage → the page should not move at all.
- Then the browser back button: it should walk back through the stages.
- Then a nav arrow with Results open.
- A driver who was eliminated in the groups: the qualifying section should
  carry a sentence and no number.

Commit message:

```
Swap results in place with HTMX; preserve disclosure state across navigation;
drop breakdown section subtotals
```
