# Tests

Lightweight jsdom-based smoke tests for the static site's frontend logic.

## Running

```bash
cd tests
npm install        # one-time, pulls jsdom
npm test
```

CI runs these on every push to main and on pull requests via
`.github/workflows/tests.yml`.

## What's covered

- **Render pipeline** — the list actually populates from `shows.json`
  data; click-targets link to Netflix.
- **Filter logic** — genre, language, region, and min-rating filters
  narrow results as expected.
- **Dialog wiring** — Support / About / Feedback buttons exist and
  open their dialogs.
- **Deploy-mismatch resilience** — strips parts of the HTML to
  simulate a cached old `index.html` paired with newer `app.js`. The
  list must still render, no fatal `TypeError`/`ReferenceError`. This
  is the regression test for the bug that caused us to add tests in
  the first place.
- **Bad data** — a `shows.json` missing the `shows` key renders the
  empty state rather than crashing.

## Why a separate `tests/package.json`?

The deployed site is fully dependency-free (no bundler, no
`package.json` at the repo root — see `CLAUDE.md` style rules). The
test harness needs `jsdom`, but isolating it under `tests/` keeps the
deploy artifact clean and the GitHub Pages publish path unchanged.
