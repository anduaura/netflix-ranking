#!/usr/bin/env python3
"""Refresh IMDb rating + votes for every entry in shows.json via OMDb.

Reads OMDB_API_KEY from the environment. Writes updated values back to
shows.json in place, preserving entry order and field order. Exits non-zero
only on hard errors (missing key, network failure on every request); per-show
lookup failures are logged and skipped so a few stale entries never block the
rest of the refresh.

Usage:
    OMDB_API_KEY=xxxx python scripts/refresh_ratings.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import date
from pathlib import Path

OMDB_URL = "http://www.omdbapi.com/"
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "shows.json"
TIMEOUT = 15
SLEEP_BETWEEN = 0.1  # be polite

# Field order preserved when rewriting each entry.
FIELD_ORDER = [
    "title", "year", "rating", "votes",
    "genres", "type", "netflix_status", "imdb_id",
]


def omdb_get(api_key: str, params: dict) -> dict | None:
    q = {"apikey": api_key, **params}
    url = OMDB_URL + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "netflix-ranking-refresh"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! request failed: {e}", file=sys.stderr)
        return None
    if data.get("Response") == "False":
        print(f"  ! OMDb: {data.get('Error', 'unknown error')}", file=sys.stderr)
        return None
    return data


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
    # Fallback: title + year.
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


def main() -> int:
    api_key = os.environ.get("OMDB_API_KEY")
    if not api_key:
        print("error: OMDB_API_KEY is not set", file=sys.stderr)
        return 2

    raw = json.loads(DATA_FILE.read_text())
    shows = raw["shows"]

    updated = 0
    skipped = 0
    failed = 0

    for i, show in enumerate(shows, 1):
        title = show["title"]
        print(f"[{i}/{len(shows)}] {title} ({show['year']})")
        data = lookup(api_key, show)
        if not data:
            failed += 1
            time.sleep(SLEEP_BETWEEN)
            continue

        new_rating = parse_rating(data.get("imdbRating"))
        new_votes = parse_votes(data.get("imdbVotes"))
        imdb_id = data.get("imdbID")

        changed = False
        if new_rating is not None and new_rating != show.get("rating"):
            print(f"  rating: {show.get('rating')} -> {new_rating}")
            show["rating"] = new_rating
            changed = True
        if new_votes is not None and new_votes != show.get("votes"):
            print(f"  votes:  {show.get('votes')} -> {new_votes}")
            show["votes"] = new_votes
            changed = True
        if imdb_id and show.get("imdb_id") != imdb_id:
            show["imdb_id"] = imdb_id
            changed = True

        if changed:
            updated += 1
        else:
            skipped += 1

        time.sleep(SLEEP_BETWEEN)

    raw["shows"] = [reorder(s) for s in shows]
    if updated > 0 or failed == 0:
        raw["updated"] = date.today().isoformat()

    DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")

    print()
    print(f"updated: {updated}  unchanged: {skipped}  failed: {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
