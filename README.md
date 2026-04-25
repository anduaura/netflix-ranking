# Netflix IMDb Ranking

An interactive ranking of Netflix originals and exclusives sorted by IMDb rating. Pure static site — no backend, no build step, deployable for free on GitHub Pages.

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

## Updating the data

Edit `shows.json`. Each entry looks like:

```json
{
  "title": "Show name",
  "year": 2020,
  "rating": 8.5,
  "votes": 250000,
  "genres": ["Drama", "Thriller"],
  "type": "series",
  "netflix_status": "original"
}
```

Allowed values:
- `type`: `series` · `limited-series` · `movie`
- `netflix_status`: `original` · `exclusive-region` · `library`

Bump the top-level `updated` field when you publish a new dataset; it's shown in the footer.

## Notes on data

Ratings are a curated, static snapshot from publicly available IMDb data. They drift over time, and Netflix availability varies by region. This site is not affiliated with Netflix or IMDb.
