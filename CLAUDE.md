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

## Donations

- Donation provider: **GitHub Sponsors** for `anduaura`. Wired via `config.js` (in-page Support button) and `.github/FUNDING.yml` (repo Sponsor button).
- Other providers (Buy Me a Coffee, Ko-fi, PayPal, custom) are configured in `config.js`; empty values hide their link.

## Style

- Static site, no build step. Vanilla HTML/CSS/JS only. Don't introduce a bundler, framework, or package.json unless asked.
- Refresh script: Python stdlib only (no `requests`, no `pip install`).
- No ads, ever.

## Adding more rules

When the user gives a durable instruction ("from now on…", "always…", "never…", "remember…"), append it here under the most relevant section so it carries across sessions.
