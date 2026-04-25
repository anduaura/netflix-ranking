#!/usr/bin/env python3
"""Grow shows.json incrementally by scanning TMDb's Netflix catalog.

Each run pulls a small slice of TMDb's "what's on Netflix" discover
results (paginated, popularity.desc) and *appends* any titles not
already in shows.json. Existing entries are never modified — that's
the ratings-refresh script's job. A scan cursor stored in shows.json
rotates through the catalog over many runs so we eventually see every
page, not just the top N.

Reads TMDB_API_KEY from the environment.

Exit codes:
  0  success (catalog possibly grew)
  2  TMDB_API_KEY not set
  3  preflight call to TMDb failed
  4  catalog at CATALOG_MAX_SIZE; nothing more to do
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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _catalog import composite_key  # noqa: E402

# ---------------------------------------------------------------------------
# Limits & knobs (single source of truth — keep CLAUDE.md in sync)
# ---------------------------------------------------------------------------

# TMDb provider/network IDs. Stable, public values.
TMDB_NETFLIX_PROVIDER = 8       # streaming-availability filter
TMDB_NETFLIX_NETWORK = 213      # Netflix as a TV network (originals)

# Catalog scope.
TMDB_REGION = "US"
TMDB_LANGUAGE = "en-US"

# How many discover pages each run inspects per media type.
# 1 page = 20 titles. Stops early if a page is empty.
TMDB_PAGES_PER_RUN = 5

# Skip entries TMDb hasn't seen enough community engagement on
# (filters obscure / unreleased content). Tunable.
TMDB_MIN_VOTE_COUNT = 50

# Safety: cap the catalog so a misconfigured run can't balloon it.
CATALOG_MAX_SIZE = 5000

# Polite pacing. TMDb's rate limit is generous (~50 req/s) but we
# don't need to sprint.
SLEEP_BETWEEN = 0.05
TIMEOUT = 15

TMDB_BASE = "https://api.themoviedb.org/3"
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "shows.json"

# Field order preserved when rewriting each entry.
FIELD_ORDER = [
    "title", "year", "rating", "votes",
    "genres", "type", "netflix_status",
    "imdb_id", "tmdb_id", "rating_refreshed_at",
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class TMDbAuthError(Exception):
    pass


def tmdb_get(api_key: str, path: str, params: dict | None = None) -> dict:
    q = {"api_key": api_key, "language": TMDB_LANGUAGE, **(params or {})}
    url = f"{TMDB_BASE}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "netflix-ranking-catalog"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        if e.code in (401, 403):
            raise TMDbAuthError(f"{e.code} {e.reason}: {body}") from None
        raise RuntimeError(f"TMDb HTTP {e.code}: {body}") from None


# ---------------------------------------------------------------------------
# Genre handling — fetch once per run.
# ---------------------------------------------------------------------------

def fetch_genre_maps(api_key: str) -> dict[str, dict[int, str]]:
    tv = tmdb_get(api_key, "/genre/tv/list")["genres"]
    movie = tmdb_get(api_key, "/genre/movie/list")["genres"]
    return {
        "tv":    {g["id"]: g["name"] for g in tv},
        "movie": {g["id"]: g["name"] for g in movie},
    }


def map_genres(ids: list[int], lookup: dict[int, str]) -> list[str]:
    return [lookup[i] for i in ids if i in lookup]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_page(api_key: str, media: str, page: int, *, network: int | None = None) -> dict:
    params = {
        "watch_region": TMDB_REGION,
        "with_watch_providers": TMDB_NETFLIX_PROVIDER,
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "page": page,
    }
    if network is not None:
        params["with_networks"] = network
    return tmdb_get(api_key, f"/discover/{media}", params)


def fetch_originals_ids(api_key: str) -> set[int]:
    """TV originals on Netflix, identified by network=213.

    Movies don't have a clean equivalent in /discover, so we mark TV
    originals only. Movies default to library (a future iteration could
    enrich via /movie/{id} production_companies).
    """
    ids: set[int] = set()
    for page in range(1, TMDB_PAGES_PER_RUN + 1):
        try:
            data = discover_page(api_key, "tv", page, network=TMDB_NETFLIX_NETWORK)
        except Exception as e:
            print(f"  ! originals page {page} failed: {e}", file=sys.stderr)
            break
        results = data.get("results") or []
        if not results:
            break
        for r in results:
            ids.add(r["id"])
        time.sleep(SLEEP_BETWEEN)
    return ids


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def year_from(date_str: str | None) -> int | None:
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def reorder(entry: dict) -> "OrderedDict[str, object]":
    out: "OrderedDict[str, object]" = OrderedDict()
    for k in FIELD_ORDER:
        if k in entry:
            out[k] = entry[k]
    for k, v in entry.items():
        if k not in out:
            out[k] = v
    return out


def index_existing(shows: list[dict]) -> tuple[dict[int, int], dict[tuple[str, int, str], int]]:
    """Return (by_tmdb_id, by_composite_key) -> index in shows list.

    The composite key folds normalized title + year + type so trivial
    title variance (case, punctuation, accents) doesn't fragment one
    show into multiple entries on first scan. See _catalog.composite_key.
    """
    by_tmdb: dict[int, int] = {}
    by_key: dict[tuple[str, int, str], int] = {}
    for i, s in enumerate(shows):
        if s.get("tmdb_id"):
            by_tmdb[int(s["tmdb_id"])] = i
        by_key[composite_key(s)] = i
    return by_tmdb, by_key


def make_entry(result: dict, media: str, genre_lookup: dict[int, str], originals_ids: set[int]) -> dict | None:
    title = result.get("name") if media == "tv" else result.get("title")
    date_field = result.get("first_air_date") if media == "tv" else result.get("release_date")
    year = year_from(date_field)
    if not title or year is None:
        return None
    if (result.get("vote_count") or 0) < TMDB_MIN_VOTE_COUNT:
        return None

    if media == "tv":
        netflix_status = "original" if result["id"] in originals_ids else "library"
        media_type = "series"
    else:
        netflix_status = "library"
        media_type = "movie"

    return {
        "title": title,
        "year": year,
        "rating": 0.0,           # placeholder; OMDb fills these in later
        "votes": 0,
        "genres": map_genres(result.get("genre_ids") or [], genre_lookup),
        "type": media_type,
        "netflix_status": netflix_status,
        "tmdb_id": result["id"],
    }


# ---------------------------------------------------------------------------
# Cursor-driven scanning
# ---------------------------------------------------------------------------

def scan_media(
    api_key: str,
    media: str,
    start_page: int,
    pages: int,
    genre_lookup: dict[int, str],
    originals_ids: set[int],
) -> tuple[list[dict], int, int]:
    """Return (new_entries, last_page_scanned, total_pages_available)."""
    new_entries: list[dict] = []
    total_pages = start_page
    last_scanned = start_page - 1
    for offset in range(pages):
        page = start_page + offset
        try:
            data = discover_page(api_key, media, page)
        except Exception as e:
            print(f"  ! /discover/{media} page {page} failed: {e}", file=sys.stderr)
            break
        total_pages = data.get("total_pages") or total_pages
        results = data.get("results") or []
        if not results:
            break
        for r in results:
            entry = make_entry(r, media, genre_lookup, originals_ids)
            if entry:
                new_entries.append(entry)
        last_scanned = page
        time.sleep(SLEEP_BETWEEN)
    return new_entries, last_scanned, total_pages


def advance_cursor(prev_cursor: int, last_scanned: int, total_pages: int) -> int:
    """Return next cursor; wrap to 1 when we run off the end."""
    nxt = last_scanned + 1
    if total_pages and nxt > total_pages:
        return 1
    if nxt < prev_cursor:  # safety
        return 1
    return nxt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        print("error: TMDB_API_KEY is not set", file=sys.stderr)
        return 2

    # Preflight: confirm the key works before we do real work.
    try:
        tmdb_get(api_key, "/configuration")
    except TMDbAuthError as e:
        print(f"FATAL: TMDb auth failed — {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"FATAL: TMDb preflight failed — {e}", file=sys.stderr)
        return 3

    raw = json.loads(DATA_FILE.read_text())
    shows: list[dict] = raw.get("shows", [])
    cursors: dict = raw.get("scan_cursors") or {"tv": 1, "movie": 1}

    if len(shows) >= CATALOG_MAX_SIZE:
        print(f"Catalog at cap ({len(shows)}/{CATALOG_MAX_SIZE}); not scanning.")
        return 4

    print(f"Catalog size before: {len(shows)}")
    print(f"Scan cursors: tv=p{cursors.get('tv', 1)} movie=p{cursors.get('movie', 1)}")

    genre_maps = fetch_genre_maps(api_key)
    originals_ids = fetch_originals_ids(api_key)
    print(f"Identified {len(originals_ids)} TV originals on this scan slice.")

    by_tmdb, by_key = index_existing(shows)
    added = 0

    for media in ("tv", "movie"):
        start = max(1, int(cursors.get(media, 1)))
        candidates, last, total = scan_media(
            api_key, media, start, TMDB_PAGES_PER_RUN,
            genre_maps[media], originals_ids,
        )
        added_for_media = 0
        for e in candidates:
            tid = e["tmdb_id"]
            if tid in by_tmdb:
                continue
            ckey = composite_key(e)
            if ckey in by_key:
                # Existing entry under a slightly different title/year —
                # backfill tmdb_id only, never overwrite ratings.
                idx = by_key[ckey]
                shows[idx].setdefault("tmdb_id", tid)
                by_tmdb[tid] = idx
                continue
            shows.append(e)
            by_tmdb[tid] = len(shows) - 1
            by_key[ckey] = len(shows) - 1
            added_for_media += 1
            added += 1
            if len(shows) >= CATALOG_MAX_SIZE:
                print(f"Hit CATALOG_MAX_SIZE={CATALOG_MAX_SIZE}; stopping.")
                break
        cursors[media] = advance_cursor(start, last, total)
        print(f"  {media}: scanned p{start}..p{last} (total_pages={total}), "
              f"candidates={len(candidates)}, added={added_for_media}, next=p{cursors[media]}")
        if len(shows) >= CATALOG_MAX_SIZE:
            break

    raw["shows"] = [reorder(s) for s in shows]
    raw["scan_cursors"] = cursors
    raw["region"] = TMDB_REGION
    raw["source"] = "Catalog discovered via TMDb (Netflix). Ratings from OMDb (IMDb)."
    if added > 0:
        raw["updated"] = date.today().isoformat()

    DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")

    print()
    print(f"Catalog size after: {len(shows)} (+{added})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
