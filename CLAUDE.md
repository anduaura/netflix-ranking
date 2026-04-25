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

- `shows.json` is refreshed daily by `.github/workflows/refresh-ratings.yml` using the `OMDB_API_KEY` repo secret.
- Manual local run: `OMDB_API_KEY=xxxx python3 scripts/refresh_ratings.py`.
- The script preserves field order and only writes when something actually changed.

## Donations

- Donation provider: **GitHub Sponsors** for `anduaura`. Wired via `config.js` (in-page Support button) and `.github/FUNDING.yml` (repo Sponsor button).
- Other providers (Buy Me a Coffee, Ko-fi, PayPal, custom) are configured in `config.js`; empty values hide their link.

## Style

- Static site, no build step. Vanilla HTML/CSS/JS only. Don't introduce a bundler, framework, or package.json unless asked.
- Refresh script: Python stdlib only (no `requests`, no `pip install`).
- No ads, ever.

## Adding more rules

When the user gives a durable instruction ("from now on…", "always…", "never…", "remember…"), append it here under the most relevant section so it carries across sessions.
