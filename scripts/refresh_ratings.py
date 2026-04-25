#!/usr/bin/env python3
"""Refresh IMDb rating + votes for the oldest slice of shows.json via OMDb.

Sharded LRU refresh: each run picks the OMDB_DAILY_BUDGET entries with the
oldest rating_refreshed_at timestamp (entries that have never been refreshed
sort first) and updates them. Over a full cycle every catalog entry is
touched; titles never refresh more than once per cycle.

Reads OMDB_API_KEY from the environment. Writes updated values back to
shows.json in place, preserving entry order and field order. A preflight
call against a known title verifies the key before iterating; auth and
quota errors abort immediately rather than burning the whole shard.

Exit codes:
  0  success (shard processed, shows possibly updated)
  2  OMDB_API_KEY not set
  3  auth failure (bad/unverified key)
  4  daily quota exhausted
  5  preflight failed for an unknown reason

Usage:
    OMDB_API_KEY=xxxx python scripts/refresh_ratings.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Limits & knobs (single source of truth — keep CLAUDE.md in sync)
# ---------------------------------------------------------------------------

# OMDb free tier: 1,000 requests/day. Reserve a margin for the preflight
# call and any incidental retries. The shard size is BUDGET - 1 (preflight
# costs 1 request).
OMDB_DAILY_BUDGET = 950

# Polite pacing between calls (seconds). OMDb has no published per-second
# rate limit but ~10 req/s is comfortable.
SLEEP_BETWEEN = 0.1

# Network timeout per OMDb call.
TIMEOUT = 15

OMDB_URL = "https://www.omdbapi.com/"
PREFLIGHT_IMDB_ID = "tt0903747"  # Breaking Bad — stable, won't disappear.
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "shows.json"

# Field order preserved when rewriting each entry.
FIELD_ORDER = [
    "title", "year", "rating", "votes",
    "genres", "type", "netflix_status",
    "original_language", "origin_country", "available_in",
    "imdb_id", "tmdb_id", "rating_refreshed_at",
]


class OMDbAuthError(Exception):
    """OMDb rejected the API key (bad key or unverified account)."""


class OMDbQuotaError(Exception):
    """OMDb's free-tier daily request cap has been hit."""


def _is_auth_error(msg: str) -> bool:
    m = msg.lower()
    return "invalid api key" in m or "no api key" in m or "unauthori" in m


def _is_quota_error(msg: str) -> bool:
    m = msg.lower()
    return "request limit reached" in m or "limit" in m and "exceeded" in m


def omdb_get(api_key: str, params: dict) -> dict | None:
    """Return parsed JSON, or None for transient/skippable errors.

    Raises OMDbAuthError / OMDbQuotaError on conditions that mean every
    subsequent call would also fail — caller should abort, not retry.
    """
    q = {"apikey": api_key, **params}
    url = OMDB_URL + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "netflix-ranking-refresh"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # OMDb sometimes returns useful JSON with a non-2xx status.
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        snippet = err_body.strip()[:300] or "(empty body)"
        if e.code == 401:
            raise OMDbAuthError(f"401 Unauthorized: {snippet}") from None
        if e.code == 402:
            raise OMDbQuotaError(f"402 Payment Required: {snippet}") from None
        print(f"  ! HTTP {e.code} {e.reason}: {snippet}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"  ! network error: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ! request failed: {e}", file=sys.stderr)
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        print(f"  ! non-JSON response ({e}): {body[:200]!r}", file=sys.stderr)
        return None

    # OMDb returns 200 OK with Response=False for both legitimate misses
    # ("Movie not found!") and fatal conditions ("Invalid API key!").
    if data.get("Response") == "False":
        err = data.get("Error", "unknown error")
        if _is_auth_error(err):
            raise OMDbAuthError(f"OMDb says: {err}")
        if _is_quota_error(err):
            raise OMDbQuotaError(f"OMDb says: {err}")
        print(f"  ! OMDb: {err}", file=sys.stderr)
        return None
    return data


def preflight(api_key: str) -> None:
    """One sanity call. Auth/quota errors propagate; misc failures fail open."""
    print(f"Preflight: testing OMDb key (length={len(api_key)})…")
    try:
        data = omdb_get(api_key, {"i": PREFLIGHT_IMDB_ID})
    except (OMDbAuthError, OMDbQuotaError):
        raise
    if not data:
        raise RuntimeError(
            "Preflight call returned no data. OMDb may be down or the response "
            "shape changed. Re-run later or inspect the logs above."
        )
    print(f"Preflight OK: matched '{data.get('Title')}' ({data.get('imdbID')}).")


def parse_votes(s: str | None) -> int | None:
    if not s or s == "N/A":
        return None
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def parse_rating(s: str | None) -> float | None:
    if not s or s == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def lookup(api_key: str, show: dict) -> dict | None:
    if show.get("imdb_id"):
        data = omdb_get(api_key, {"i": show["imdb_id"]})
        if data:
            return data
    return omdb_get(api_key, {"t": show["title"], "y": show["year"]})


def reorder(entry: dict) -> "OrderedDict[str, object]":
    out: "OrderedDict[str, object]" = OrderedDict()
    for k in FIELD_ORDER:
        if k in entry:
            out[k] = entry[k]
    for k, v in entry.items():
        if k not in out:
            out[k] = v
    return out


def select_shard(shows: list[dict], budget: int) -> tuple[list[dict], list[int]]:
    """Return (shard_entries, original_indices) — oldest rating_refreshed_at first.

    Entries with no timestamp sort first (treated as infinitely stale), so a
    freshly-grown catalog is fully refreshed before any rotation starts.
    """
    if budget <= 0 or not shows:
        return [], []
    indexed = list(enumerate(shows))
    # Empty string sorts before any ISO-8601 string, which is exactly what we
    # want for "never refreshed".
    indexed.sort(key=lambda pair: pair[1].get("rating_refreshed_at") or "")
    chosen = indexed[:budget]
    return [s for _, s in chosen], [i for i, _ in chosen]


def main() -> int:
    api_key = os.environ.get("OMDB_API_KEY")
    if not api_key:
        print("error: OMDB_API_KEY is not set", file=sys.stderr)
        return 2

    try:
        preflight(api_key)
    except OMDbAuthError as e:
        print(f"\nFATAL: OMDb auth failed — {e}", file=sys.stderr)
        print(
            "Most common cause: the OMDb account hasn't been verified yet. "
            "Check your inbox for the activation email from omdbapi.com and "
            "click VERIFY ACCOUNT, or confirm OMDB_API_KEY in repo secrets "
            "matches the verified key.",
            file=sys.stderr,
        )
        return 3
    except OMDbQuotaError as e:
        print(f"\nFATAL: OMDb quota exhausted — {e}", file=sys.stderr)
        print("Free tier is 1,000 requests/day. Try again tomorrow UTC.", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"\nFATAL: preflight failed — {e}", file=sys.stderr)
        return 5

    raw = json.loads(DATA_FILE.read_text())
    shows = raw["shows"]

    shard, shard_indices = select_shard(shows, OMDB_DAILY_BUDGET - 1)
    if not shard:
        print("Catalog is empty; nothing to refresh.")
        return 0

    print(
        f"Shard: {len(shard)}/{len(shows)} entries selected "
        f"(budget={OMDB_DAILY_BUDGET}, full-cycle ≈ "
        f"{(len(shows) + (OMDB_DAILY_BUDGET - 1) - 1) // max(OMDB_DAILY_BUDGET - 1, 1)} runs)."
    )

    updated = 0
    skipped = 0
    failed = 0

    try:
        for i, (show, idx) in enumerate(zip(shard, shard_indices), 1):
            title = show["title"]
            print(f"[{i}/{len(shard)}] {title} ({show.get('year', '?')})")
            data = lookup(api_key, show)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if not data:
                failed += 1
                # Still stamp it so a permanently-unmatchable entry doesn't
                # monopolize every shard. Site UX is better off touching the
                # next stale entry instead.
                shows[idx]["rating_refreshed_at"] = now
                time.sleep(SLEEP_BETWEEN)
                continue

            new_rating = parse_rating(data.get("imdbRating"))
            new_votes = parse_votes(data.get("imdbVotes"))
            imdb_id = data.get("imdbID")

            changed = False
            if new_rating is not None and new_rating != show.get("rating"):
                print(f"  rating: {show.get('rating')} -> {new_rating}")
                shows[idx]["rating"] = new_rating
                changed = True
            if new_votes is not None and new_votes != show.get("votes"):
                print(f"  votes:  {show.get('votes')} -> {new_votes}")
                shows[idx]["votes"] = new_votes
                changed = True
            if imdb_id and show.get("imdb_id") != imdb_id:
                shows[idx]["imdb_id"] = imdb_id
                changed = True

            shows[idx]["rating_refreshed_at"] = now
            if changed:
                updated += 1
            else:
                skipped += 1

            time.sleep(SLEEP_BETWEEN)
    except OMDbAuthError as e:
        # Key got revoked mid-run; bail without writing partial garbage.
        print(f"\nFATAL: OMDb auth failed mid-run — {e}", file=sys.stderr)
        return 3
    except OMDbQuotaError as e:
        print(f"\nFATAL: OMDb quota exhausted mid-run — {e}", file=sys.stderr)
        # Still write what we have so far so the run isn't wasted.
        raw["shows"] = [reorder(s) for s in shows]
        DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        print(f"partial save: updated={updated} skipped={skipped}", file=sys.stderr)
        return 4

    raw["shows"] = [reorder(s) for s in shows]
    if updated > 0 or failed == 0:
        raw["updated"] = date.today().isoformat()

    DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")

    print()
    print(f"updated: {updated}  unchanged: {skipped}  failed: {failed}  "
          f"(shard={len(shard)}, catalog={len(shows)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
