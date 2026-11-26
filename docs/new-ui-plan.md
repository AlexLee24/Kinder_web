# New UI: whole-site mobile + UI pass

Branch `new-ui` (from master after #156). One commit per area; one PR `new-ui` -> `master` at the end (draft while in progress).

## Method, every page

1. **Phone**: iOS Simulator (iPhone, Safari) screenshots of every section and every window; the browser at 375 px clicks
   every button that does not change data (delete / send / save / trigger are opened but not confirmed) and checks for
   errors, sideways scroll and content past the screen.
2. **Desktop**: 1280x800, 1440x900, 1920x1080 screenshots; same sweep.
3. **modern-web-guidance**: windows as native `<dialog>` (no page scroll behind), 44 px touch targets that do not break
   custom controls, safe areas, form labels, tables on small screens.
4. **unslop / ui-ux-pro-max**: one type scale (11-16 px body), sentence case, weights up to 600, no glow, one accent,
   aligned rows, nothing moves when a button is pressed (space reserved, new content added below).
5. **PulsoIcon**: `kinder_icons.js` loaded site-wide from the shell; every inline icon mapped (static at rest, motion on
   hover / focus, none with reduced motion); no emoji.
6. Look at every screenshot before calling a page done (a scripted sweep does not catch a distorted control).

## Order

| # | Area | Pages |
|---|------|-------|
| 0 | Shell | header, sidebar, phone tab bar, install banner, notifications, user menu |
| 1 | Account | `/`, `/login`, `/profile`, `/settings`, `/account/password`, `/offline` |
| 2 | Marshal | `/marshal`, Transient page `/object/<name>` |
| 3 | DETECT | `/detect`, archives, crossmatch, lens/sugohi, LSST, LSST review, LSST archives |
| 4 | Triggers | `/direct_trigger`, `/bots` (Alerts) |
| 5 | Planning and tools | `/astronomy_tools`, observation / interactive planner, finding chart, LC plotter, ETC, spectrum, sky cutouts, telescope simulator, mount 3D / torque, CASTOR S/N check, new SLT |
| 6 | Lab | calendar, pipeline (+ reduction, telescopes), special run (+ Euclid SLSN, lens sim), ePESSTO+, Lab info, documents, games |
| 7 | Admin | panel, bots, database, log, permissions, push, routines, site, Slack, system |

## Redesign

Allowed, but only after asking with two or more demos. Direction is asked once for the shell (it sets every page);
per-page redesigns, if any, are asked when that page comes up.
