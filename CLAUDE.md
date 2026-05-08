# Project rules for Claude

These rules apply to every session in this repo. Read them before doing any work.

## Git authorship & messages

- **Commit author + committer must be:** `Andu <andu.ucsd@gmail.com>`. Do not commit as Claude or any Anthropic identity. The repo's local `user.name` / `user.email` are already set; do not change them.
- **Never include the `https://claude.ai/code/...` session link** (or any Claude/Anthropic attribution) in commit messages, PR titles/bodies, or code comments.
- Bot commits from CI (`github-actions[bot]`) are allowed and should not be rewritten.
- If you ever notice a Claude-attributed commit slipping in (e.g. config drift), rewrite it before pushing.

## Branching

- Work directly on `main`. Push commits straight there.
- Don't create feature branches or PRs unless explicitly asked.

## Deployment

- The site auto-deploys to GitHub Pages on every push to `main` via `.github/workflows/pages.yml`.
- Live URL: https://showranks.com (custom domain set via the `CNAME` file at repo root). The GitHub Pages default `https://anduaura.github.io/netflix-ranking/` redirects to the custom domain once Pages applies the setting.
- After pushing user-visible changes, you can verify by curling that URL once Pages has had ~30–60s to redeploy.

## Data refresh

`.github/workflows/refresh-ratings.yml` runs daily at 06:00 UTC and chains two scripts:

1. **`scripts/refresh_catalog.py`** — grows `shows.json` incrementally from TMDb's Netflix discover endpoint using a rotating page cursor stored inside the file. Existing entries are never modified by this step. Requires `TMDB_API_KEY` secret; if missing, the step is skipped (warning, not failure).
2. **`scripts/refresh_ratings.py`** — sharded LRU refresh of IMDb ratings via OMDb. Picks the `OMDB_DAILY_BUDGET` entries with the oldest `rating_refreshed_at` and updates them. Requires `OMDB_API_KEY` secret.

The workflow's `actions/checkout` step authenticates with `secrets.BOT_PUSH_TOKEN` — a fine-grained PAT owned by the repo admin (`anduaura`). Required because the `main` branch ruleset requires PRs from non-admin actors, and the default `GITHUB_TOKEN` pushes as `github-actions[bot]`, which isn't a bypass actor in personal-repo rulesets. The PAT inherits the admin bypass entry and can push directly. If the PAT ever needs to be rotated, the only place to update is the secret value at `Settings → Secrets and variables → Actions → BOT_PUSH_TOKEN`.

**Architectural rules:**
- **Limits are named constants** at the top of each script (`OMDB_DAILY_BUDGET`, `TMDB_PAGES_PER_RUN`, `TMDB_MIN_VOTE_COUNT`, `CATALOG_MAX_SIZE`, `TMDB_REGION`, etc.). Never inline magic numbers in the body of the scripts. When tuning, change the constant.
- **Fail fast on auth/quota errors** (exit codes 3 / 4). Never retry through a doomed budget.
- **Preserve field order** when rewriting entries (`FIELD_ORDER` constant).
- **Catalog growth is append-only.** Don't remove entries based on TMDb absence — Netflix availability flaps.
- **Stamp `rating_refreshed_at` even on lookup failures** so a permanently-unmatchable entry doesn't monopolize every shard.

Manual local run:
```bash
TMDB_API_KEY=xxxx python3 scripts/refresh_catalog.py
OMDB_API_KEY=yyyy python3 scripts/refresh_ratings.py
```

## Design decisions (revisit when iterating)

These document *why* the data pipeline looks the way it does. If a constraint changes (paid OMDb tier, larger catalog goal, multi-region, etc.), revisit the decision listed here rather than tweaking ad hoc.

### Two API providers, separated by responsibility
- **TMDb** for catalog discovery (what's on Netflix in a given region). Free, generous limits, region-aware.
- **OMDb** for IMDb rating + vote count enrichment. TMDb does not expose IMDb ratings; OMDb does.
- Each provider gets its own script and its own secret. Either can fail without disabling the other.
- Rejected: scraping IMDb / Netflix directly (ToS + brittleness). Rejected: TMDb's own `vote_average` (different audience, drifts from IMDb).

### Catalog growth: incremental append-only with a rotating page cursor
- Each run scans `TMDB_PAGES_PER_RUN` discover pages per media type starting from `scan_cursors[media]`, then advances the cursor. Wraps to page 1 when it runs off the end.
- **Why incremental, not full re-pull:** TMDb popularity ranking flaps; full re-pulls would churn the catalog. Append-only avoids losing titles that temporarily dropped off Netflix or off the popularity tail.
- **Why rotate the cursor:** without it we'd re-scan the same top pages forever and never discover the long tail.
- **Why not `first_air_date.desc` to find new releases instead:** misses popular catalog titles that exist but weren't seeded. Rotating popularity sweep eventually finds everything.
- **Quality floor:** `TMDB_MIN_VOTE_COUNT=50` skips obscure / unreleased TMDb entries. Bump down to be more inclusive, up to be stricter.
- **Hard ceiling:** `CATALOG_MAX_SIZE=5000` prevents runaway growth. Free OMDb refreshes fully cycle a 5k catalog in ~6 days at 950/day.

### Ratings refresh: sharded LRU keyed by `rating_refreshed_at`
- Each run picks the `OMDB_DAILY_BUDGET - 1` entries with the oldest timestamp (entries with no timestamp sort first). Preflight uses 1 of the budget.
- **Why LRU over popularity-weighted:** simple, fair, and survives catalog growth without any new tuning. Every title eventually refreshes; new titles get prioritized.
- **Why stamp the timestamp on failures too:** otherwise a permanently-unmatchable entry (e.g. weird title that OMDb can't resolve) monopolizes every shard forever. Stamping moves it to the back of the line.
- **Why budget = 950 (not 1000):** OMDb's free cap is 1k/day; reserving ~50 covers the preflight + any incidental retries + a buffer for the existing-data UI to also hit OMDb if we ever add that.
- **Why no concurrency:** OMDb has no published rate limit but `SLEEP_BETWEEN=0.1` keeps us conservative. Adding a thread pool buys minutes per run, not hours.

### Availability enrichment & cooldown
- After the catalog growth pass, `refresh_catalog.py` calls `/watch/providers` per entry to populate `available_in` (regions where Netflix carries it as a flatrate provider). This drives the UI's region filter.
- **`ENRICH_COOLDOWN_DAYS = 7`**: an entry that already has `available_in` is skipped for 7 days after its last `enriched_at` stamp. Avoids hammering TMDb daily for data that rarely changes.
- **`MAX_ENRICHMENT_FAILURES = 2`**: incomplete entries (missing `available_in`) retry on every run *up to* this many consecutive failed attempts. After hitting the cap, the entry is parked until `ENRICH_COOLDOWN_DAYS` passes; then the counter resets and it gets a fresh budget. Stops the script from hammering TMDb forever for titles that genuinely have no provider data.
- **Stamp every attempt** — successes and failures both write `enriched_at = now`. Successes also clear `enrichment_failures` (it's irrelevant once we have data). Failures increment it.
- **Decision matrix** for whether to enrich an entry on a given run:
  | `available_in` | last `enriched_at` | `enrichment_failures` | action |
  |---|---|---|---|
  | present | ≤ 7d | any | skip (cooldown) |
  | present | > 7d | any | re-enrich |
  | missing | any | < 2 | retry |
  | missing | ≤ 7d | ≥ 2 | skip (parked) |
  | missing | > 7d | ≥ 2 | reset counter, retry |
  | absent  | n/a | n/a | enrich |
- **One-time migration:** entries that already have `available_in` but no `enriched_at` (added before the cooldown shipped) get `enriched_at = now` at script start, so the cooldown immediately protects them without an extra round of redundant calls.
- **`MAX_ENRICH_PER_RUN = 1000`** caps per-run cost. Catalog can't currently approach that.
- **Merge logic:** when duplicates merge, if either side has `available_in` the failures counter is dropped (success makes it meaningless); if neither side has data, the lower count wins (more optimistic).

### Identity & deduplication
- **Two-tier identity:** `tmdb_id` (canonical, exact) + composite key `(normalize_title(title), year, type)` for entries without one. Both live in `scripts/_catalog.py` — never reimplement them inline.
- **`normalize_title`** strips diacritics, lowercases, drops punctuation, collapses whitespace. So `"Spider-Man: Across the Spider-Verse"`, `"Spider-Man Across the Spider-Verse"`, and `"  spider man across the spider verse "` all hash to one key. `"Élite"` and `"Elite"` collapse together; `"Money Heist"` and `"La Casa de Papel"` deliberately do not (different strings → different content under our model; merging across translations requires `tmdb_id`).
- **`type` is part of the composite key** so a movie and a series sharing title+year don't false-merge.
- **Hot-path dedup in `refresh_catalog.py`** uses both indices: tmdb_id collision skips, composite-key collision backfills `tmdb_id` onto the existing row without touching ratings.
- **One-shot dedupe pass: `scripts/dedupe_catalog.py`.** Detects intra-catalog duplicates via union-find over (same tmdb_id) ∪ (same composite key). Mergeable groups are merged via `merge_entries`; groups with multiple distinct `tmdb_id`s are flagged as **conflicts** and left untouched (manual review). Run on demand: `python3 scripts/dedupe_catalog.py [--dry-run]`. Exits 1 if any conflicts remain.
- **`merge_entries`** rules (deterministic, order-independent):
  - title/year/type → first entry sorted by `(has tmdb_id, has imdb_id, -votes, -rating)` wins
  - rating, votes → max non-zero
  - genres → sorted union
  - netflix_status → highest-priority label (`original > exclusive-region > library`)
  - imdb_id, tmdb_id → any non-empty
  - rating_refreshed_at → most recent (ISO-8601-Z compares correctly as a string)
- **Why we don't auto-merge across distinct tmdb_ids:** TMDb occasionally has duplicate listings, but more often two entries with the same composite key + different tmdb_ids are genuinely different content (anthology, reboot using the same name). Picking silently is worse than asking.

### Schema decisions
- `tmdb_id` and `imdb_id` are both stored. TMDb is canonical for catalog identity (matches the discovery source); IMDb id makes OMDb lookups exact (no title+year fuzzy matching).
- `rating_refreshed_at` is ISO-8601 UTC with `Z` suffix — stable, sortable as a string, no timezone gymnastics.
- `netflix_status` distinguishes `original` / `library` / `exclusive-region`. We currently only auto-detect TV originals (via `with_networks=213`). Movies default to `library`. Future: enrich movies via `/movie/{id}/?append_to_response=production_companies` and check for Netflix.
- Top-level `scan_cursors` is per-media (`tv`, `movie`) so the two cycle independently.

### Region scope (multi-region rotating)
- `TMDB_REGIONS` constant (currently `["US", "KR", "JP", "VN"]`) drives discovery scope. TMDb's `with_watch_providers` filter is region-specific, so each region gets scanned independently.
- **Two-axis rotation:**
  - **Page cursor per (region, media):** stored in `shows.json` as `scan_cursors[region][media]`. Advances by `TMDB_PAGES_PER_RUN` each time the region is scanned.
  - **Region cursor:** stored as `scan_cursors["region_cursor"]` (an integer index into `TMDB_REGIONS`). Each run picks the next `TMDB_REGIONS_PER_RUN` regions starting from this cursor and advances modulo `len(TMDB_REGIONS)`.
- **`TMDB_REGIONS_PER_RUN`** is the polite/aggressive knob: set to `len(TMDB_REGIONS)` for fastest growth (every region every run, default), set to `1` to scan one region per run if TMDb-side concerns or daily-budget pressure ever matter.
- **Cross-region dedup is automatic** — `composite_key` collapses overlapping titles (e.g. *Squid Game* surfacing in both US and KR scans) into one entry. No per-region availability is tracked; the site says "on Netflix" without specifying where.
- **Schema migration:** `migrate_cursors()` accepts the legacy `{tv, movie}` shape (treated as `TMDB_REGIONS[0]` cursors) and the new per-region shape, backfilling missing regions to page 1. Safe to add or remove regions in `TMDB_REGIONS` between runs.
- **TV originals detection (`with_networks=213`)** is region-independent — Netflix's network ID is global, so we run it once per scan slice, not per-region.

### Deploy chain (workflow_run)
- `pages.yml` listens to `workflow_run` after `Refresh catalog and ratings` completes successfully. Required because GitHub deliberately blocks workflow chains from `GITHUB_TOKEN`-pushed commits — without this trigger, bot-pushed catalog/ratings updates would never reach Pages.
- `pages.yml` also keeps its `push: branches: [main]` and `workflow_dispatch` triggers for manual / human-driven deploys.
- The `if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'` guard prevents redeploying after failed refresh runs.

### Workflow shape
- Single workflow with two steps so a catalog growth + ratings refresh land in the same commit.
- TMDb step is conditional (`if: env.TMDB_API_KEY != ''`) so the workflow keeps working even if only the OMDb secret is set. Soft-fail with a `::warning::` annotation, not hard-fail.
- Catalog step runs first so the ratings step sees newly-added entries (with empty `rating_refreshed_at`) and prioritizes them automatically via the LRU sort.

### Things deliberately NOT done (yet)
- **No popularity-weighted refresh.** A future option: refresh top-N popular titles every run plus LRU for the tail. Adds a constant `POPULAR_PIN_COUNT` and a popularity score in entries.
- **No movie-originals detection.** Costs N extra TMDb detail calls per discovered movie. Defer until the catalog is large enough that the missing distinction is annoying.
- **No catalog pruning.** We never remove entries that drop off Netflix. Cheap to add (mark `removed_at` on absence over N consecutive scans), but flapping is a real risk.
- **No content posters / images.** Site is text-only by design; adding images means TMDb image CDN + lazy loading + larger payload. Reconsider only if there's user demand.

## Donations

- Donation provider: **GitHub Sponsors** for `anduaura`. Wired via `config.js` (in-page Support button) and `.github/FUNDING.yml` (repo Sponsor button).
- Other providers (Buy Me a Coffee, Ko-fi, PayPal, custom) are configured in `config.js`; empty values hide their link.

## Feedback form

- The Feedback dialog's "Send" button POSTs straight to **FormSubmit** (`https://formsubmit.co/ajax/<email>`) so users never leave the site. Free, no signup, no backend.
- **First-time activation:** the very first submission triggers FormSubmit to email the recipient (`andu.ucsd@gmail.com`) with a confirmation link. Until that link is clicked once, submissions go nowhere. After activation, all future submissions pass through silently.
- If the email is rotated or the recipient changes, update `config.js → feedback.email` and re-activate FormSubmit on the new address.
- The "Or open as GitHub issue" link is a non-FormSubmit fallback that opens a prefilled issue creation page on the repo. Always works regardless of FormSubmit state.
- A hidden honeypot field deters basic bot submissions; FormSubmit also has built-in spam protection. Captcha is disabled (`_captcha: false`) for UX; bump it on if abuse becomes a problem.

## Style

- Static site, no build step. Vanilla HTML/CSS/JS only. Don't introduce a bundler, framework, or package.json *at the repo root*. The `tests/` directory has its own `package.json` for jsdom — that's allowed because it doesn't affect the deployed artifact.
- Refresh script: Python stdlib only (no `requests`, no `pip install`).
- No ads, ever.

## Tests

- `tests/` directory holds jsdom-based smoke tests for the frontend (`tests/test_app.js`).
- Run locally: `cd tests && npm install && npm test`.
- CI: `.github/workflows/tests.yml` runs on every push to main + every PR. Tests are scoped via `paths:` so data-only commits (bot ratings refresh) don't trigger them.
- **Coverage focus** — these are intentionally smoke tests, not full unit tests. They catch:
  - Rendering pipeline broken end-to-end ("list disappeared")
  - Setup functions throwing when elements missing (deploy mismatch: cached old HTML + new JS)
  - Filter logic regressions
  - Dialog wiring (Support/About/Feedback)
  - Bad data tolerance (missing `shows` key)
- **When adding a new feature**, add a test that would have caught its absence. Don't over-fit — one or two assertions per feature is enough.

## Adding more rules

When the user gives a durable instruction ("from now on…", "always…", "never…", "remember…"), append it here under the most relevant section so it carries across sessions.
