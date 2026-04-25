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
- Live URL: https://anduaura.github.io/netflix-ranking/
- After pushing user-visible changes, you can verify by curling that URL once Pages has had ~30–60s to redeploy.

## Data refresh

`.github/workflows/refresh-ratings.yml` runs daily at 06:00 UTC and chains two scripts:

1. **`scripts/refresh_catalog.py`** — grows `shows.json` incrementally from TMDb's Netflix discover endpoint using a rotating page cursor stored inside the file. Existing entries are never modified by this step. Requires `TMDB_API_KEY` secret; if missing, the step is skipped (warning, not failure).
2. **`scripts/refresh_ratings.py`** — sharded LRU refresh of IMDb ratings via OMDb. Picks the `OMDB_DAILY_BUDGET` entries with the oldest `rating_refreshed_at` and updates them. Requires `OMDB_API_KEY` secret.

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

### Schema decisions
- `tmdb_id` and `imdb_id` are both stored. TMDb is canonical for catalog identity (matches the discovery source); IMDb id makes OMDb lookups exact (no title+year fuzzy matching).
- `rating_refreshed_at` is ISO-8601 UTC with `Z` suffix — stable, sortable as a string, no timezone gymnastics.
- `netflix_status` distinguishes `original` / `library` / `exclusive-region`. We currently only auto-detect TV originals (via `with_networks=213`). Movies default to `library`. Future: enrich movies via `/movie/{id}/?append_to_response=production_companies` and check for Netflix.
- Top-level `scan_cursors` is per-media (`tv`, `movie`) so the two cycle independently.

### Region scope
- Default `TMDB_REGION="US"`. TMDb's `with_watch_providers` filter is region-specific; "Netflix" in Brazil ≠ Netflix in the US.
- **Future iteration:** if we want multi-region, add `regions: [...]` to the workflow input or env, fan out catalog growth per region, and add a `regions` array per show entry. Schema is forward-compatible.

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

## Style

- Static site, no build step. Vanilla HTML/CSS/JS only. Don't introduce a bundler, framework, or package.json unless asked.
- Refresh script: Python stdlib only (no `requests`, no `pip install`).
- No ads, ever.

## Adding more rules

When the user gives a durable instruction ("from now on…", "always…", "never…", "remember…"), append it here under the most relevant section so it carries across sessions.
