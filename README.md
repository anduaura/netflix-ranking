# Netflix IMDb Ranking

An interactive ranking of Netflix originals and exclusives sorted by IMDb rating. Pure static site — no backend, no build step, deployable for free on GitHub Pages.

**Live site:** https://anduaura.github.io/netflix-ranking/

## Features

- Sort by rating, votes, year, or title
- Filter by genre, type (series / limited series / movie), and Netflix status
- Minimum rating slider
- Live search
- Filter state synced to the URL (shareable links)
- Click any title to jump to IMDb
- Dark, Netflix-inspired UI; mobile-friendly

## Project layout

```
index.html      # markup + filter controls
styles.css      # dark theme
app.js          # filter / sort / render logic
shows.json      # the dataset (edit me to add shows)
.github/workflows/pages.yml   # auto-deploys to GitHub Pages on push to main
```

## Run locally

It's a plain static site, but `fetch("shows.json")` needs an HTTP origin (it won't work from `file://`). Use any tiny static server, e.g.:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Publish for the world (GitHub Pages)

This repo ships with a workflow that publishes the site automatically.

1. Push this code to GitHub (the workflow runs on `main`).
2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Merge `claude/netflix-ranking-site-jeHqx` into `main` (or change the workflow's `branches` line if you want to publish from another branch).
4. Once the workflow finishes, your site is live at `https://<user>.github.io/<repo>/`.

## shows.json schema

Each entry looks like:

```json
{
  "title": "Show name",
  "year": 2020,
  "rating": 8.5,
  "votes": 250000,
  "genres": ["Drama", "Thriller"],
  "type": "series",
  "netflix_status": "original",
  "imdb_id": "tt1234567",
  "tmdb_id": 98765,
  "rating_refreshed_at": "2026-04-25T06:00:00Z"
}
```

- `type`: `series` · `limited-series` · `movie`
- `netflix_status`: `original` · `exclusive-region` · `library`
- `rating_refreshed_at`: drives LRU sharding for the daily ratings refresh.

Top-level fields:

```json
{
  "updated": "2026-04-25",
  "region": "US",
  "scan_cursors": { "tv": 6, "movie": 11 },
  "shows": [ ... ]
}
```

You can hand-edit `shows.json`, but typically you'll let the workflow grow and refresh it.

## Auto-updating data (catalog + ratings)

Two scripts run daily in the same workflow (`.github/workflows/refresh-ratings.yml`):

1. **Catalog grower** — `scripts/refresh_catalog.py` scans a few pages of [TMDb](https://www.themoviedb.org/)'s Netflix discover endpoint and **appends** any new titles to `shows.json`. A page cursor stored in the file rotates through the catalog over many runs, so the library grows incrementally toward a complete Netflix index.
2. **Sharded ratings refresh** — `scripts/refresh_ratings.py` picks the `OMDB_DAILY_BUDGET` entries with the oldest `rating_refreshed_at` (LRU) and updates ratings + votes via [OMDb](https://www.omdbapi.com/). Over a full cycle every catalog entry is touched.

**Limits live as named constants** at the top of each script (`TMDB_PAGES_PER_RUN`, `TMDB_MIN_VOTE_COUNT`, `CATALOG_MAX_SIZE`, `OMDB_DAILY_BUDGET`, etc.). Tune those in one place — don't sprinkle magic numbers.

**Set it up:**

1. **OMDb key** — free at https://www.omdbapi.com/apikey.aspx (1,000 req/day). Store as repo secret `OMDB_API_KEY`. **You must click the verification email**, otherwise every call returns 401.
2. **TMDb key** — free at https://www.themoviedb.org/settings/api. Store as repo secret `TMDB_API_KEY`. (Optional — if missing, catalog growth is skipped and only the existing entries get rating refreshes.)
3. The workflow runs daily at 06:00 UTC and on manual dispatch. When `shows.json` changes, it commits to `main`, which triggers the Pages deploy.

**Run locally:**

```bash
TMDB_API_KEY=xxxx python3 scripts/refresh_catalog.py
OMDB_API_KEY=yyyy python3 scripts/refresh_ratings.py
```

Each script saves what it has on partial failures (network blips, mid-run quota exhaustion) so a flaky day doesn't waste prior progress.

**Dedupe pass (on demand):**

```bash
python3 scripts/dedupe_catalog.py --dry-run   # preview
python3 scripts/dedupe_catalog.py             # write merges
```

Detects duplicate entries by composite key `(normalized_title, year, type)`, merges the safe ones (via `scripts/_catalog.merge_entries`), and flags conflicts (same composite key, different `tmdb_id`s) for manual review.

## Donations / supporting the site

The site is ad-free. A **♥ Support** button in the header opens a small modal pointing at [GitHub Sponsors](https://github.com/sponsors/anduaura), and `.github/FUNDING.yml` enables GitHub's native "Sponsor" button on the repo page.

Want to add Buy Me a Coffee, Ko-fi, PayPal, or a custom destination later? Drop the relevant handle into `config.js` (any field you leave empty is hidden in the UI; if every field is empty, the Support button disappears entirely).

## Notes on data

Ratings come from IMDb (via OMDb when the refresh workflow is enabled). Netflix availability varies by region. This site is not affiliated with Netflix or IMDb.

## License

The code in this repository is licensed under the [MIT License](./LICENSE) — © 2026 Andu.

The **data** in `shows.json` is a separate matter: it's derived from third-party APIs ([TMDb](https://www.themoviedb.org/) for catalog discovery and watch-provider availability, [OMDb](https://www.omdbapi.com/) for IMDb ratings) and is governed by their respective terms of service, not the MIT license above. Notably, OMDb's free tier is intended for non-commercial use; treat the data accordingly if you fork this and run it at scale.

