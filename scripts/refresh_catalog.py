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

# Regions to scan, in order. Each region has its own scan cursor stored in
# shows.json so they advance independently. Add codes here to expand the
# catalog (e.g. "GB", "IN"); remove to narrow it.
TMDB_REGIONS = ["US", "KR", "JP"]

# How many regions get scanned per run. The script rotates through
# TMDB_REGIONS in order, scanning this many per run starting from the
# stored region cursor. Set to len(TMDB_REGIONS) to scan everything every
# run; set to 1 to be polite (one region per day).
TMDB_REGIONS_PER_RUN = 3

# TMDb response language. Affects returned title spelling; doesn't
# restrict which content is returned.
TMDB_LANGUAGE = "en-US"

# How many discover pages each run inspects per (region, media) combo.
# 1 page = 20 titles. Stops early if a page is empty.
TMDB_PAGES_PER_RUN = 5

# Skip entries TMDb hasn't seen enough community engagement on
# (filters obscure / unreleased content). Tunable.
TMDB_MIN_VOTE_COUNT = 50

# Safety: cap the catalog so a misconfigured run can't balloon it.
CATALOG_MAX_SIZE = 5000

# How many entries get enriched with /watch/providers per run. Drives the
# `available_in` field that powers the UI's region filter. TMDb's free
# tier has no daily cap so this can be large; we just don't want one run
# to hang for 20 minutes if the catalog ever gets huge. Set to 0 to
# disable availability enrichment entirely.
MAX_ENRICH_PER_RUN = 1000

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
    "original_language", "origin_country", "available_in",
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

def discover_page(api_key: str, media: str, page: int, region: str, *, network: int | None = None) -> dict:
    params = {
        "watch_region": region,
        "with_watch_providers": TMDB_NETFLIX_PROVIDER,
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "page": page,
    }
    if network is not None:
        params["with_networks"] = network
    return tmdb_get(api_key, f"/discover/{media}", params)


def fetch_availability(api_key: str, tmdb_id: int, media: str) -> list[str] | None:
    """Return regions where Netflix is a flatrate (subscription) provider.

    Returns [] if Netflix isn't on any region's provider list (rare but
    possible — TMDb may know about a title without watch-provider data).
    Returns None on hard failure so callers can leave the field unset
    and retry later.
    """
    path = "tv" if media in ("tv", "series", "limited-series") else "movie"
    try:
        data = tmdb_get(api_key, f"/{path}/{tmdb_id}/watch/providers")
    except Exception as e:
        print(f"  ! providers {path}/{tmdb_id}: {e}", file=sys.stderr)
        return None

    found: list[str] = []
    for region, info in (data.get("results") or {}).items():
        flatrate = info.get("flatrate") or []
        for provider in flatrate:
            if provider.get("provider_id") == TMDB_NETFLIX_PROVIDER:
                found.append(region)
                break
    return sorted(found)


def fetch_originals_ids(api_key: str) -> set[int]:
    """TV originals on Netflix, identified by network=213.

    Region-independent — Netflix's network id is global. We scan a few
    pages here just to seed the originals lookup; titles missed at this
    step still appear in catalog growth, they'll just default to
    'library' until a future scan catches them.

    Movies don't have a clean equivalent in /discover, so we mark TV
    originals only. Movies default to library (a future iteration could
    enrich via /movie/{id} production_companies).
    """
    ids: set[int] = set()
    # Use the first region as the "watch_region" for this query — it
    # doesn't matter much because with_networks=213 is the real filter.
    region = TMDB_REGIONS[0] if TMDB_REGIONS else "US"
    for page in range(1, TMDB_PAGES_PER_RUN + 1):
        try:
            data = discover_page(api_key, "tv", page, region, network=TMDB_NETFLIX_NETWORK)
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

    entry: dict = {
        "title": title,
        "year": year,
        "rating": 0.0,           # placeholder; OMDb fills these in later
        "votes": 0,
        "genres": map_genres(result.get("genre_ids") or [], genre_lookup),
        "type": media_type,
        "netflix_status": netflix_status,
        "tmdb_id": result["id"],
    }
    if result.get("original_language"):
        entry["original_language"] = result["original_language"]
    if media == "tv":
        # /discover/tv returns origin_country; /discover/movie does not.
        oc = result.get("origin_country") or []
        if oc:
            entry["origin_country"] = list(oc)
    return entry


# ---------------------------------------------------------------------------
# Cursor-driven scanning
# ---------------------------------------------------------------------------

def scan_media(
    api_key: str,
    media: str,
    region: str,
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
            data = discover_page(api_key, media, page, region)
        except Exception as e:
            print(f"  ! /discover/{media} {region} page {page} failed: {e}", file=sys.stderr)
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


def migrate_cursors(stored: dict | None) -> dict:
    """Normalize the on-disk cursor blob into per-region structure.

    Three shapes we accept on input:
      None or {}            → fresh start, all regions at p1
      {"tv": N, "movie": M} → legacy single-region; assumed to be the
                              first region in TMDB_REGIONS, others at p1
      {"US": {...}, ...}    → already per-region; passed through, missing
                              regions backfilled at p1
    """
    out: dict[str, dict[str, int]] = {r: {"tv": 1, "movie": 1} for r in TMDB_REGIONS}
    if not stored:
        return out
    if "tv" in stored or "movie" in stored:
        legacy_region = TMDB_REGIONS[0] if TMDB_REGIONS else "US"
        out[legacy_region] = {
            "tv": int(stored.get("tv", 1)),
            "movie": int(stored.get("movie", 1)),
        }
        return out
    for region, cur in stored.items():
        if not isinstance(cur, dict):
            continue
        out[region] = {
            "tv": int(cur.get("tv", 1)),
            "movie": int(cur.get("movie", 1)),
        }
    return out


def select_regions_for_run(stored: dict, count: int) -> tuple[list[str], int]:
    """Pick the next `count` regions starting from stored region cursor.

    Returns (regions_to_scan, next_region_cursor).
    """
    if not TMDB_REGIONS:
        return [], 0
    n = len(TMDB_REGIONS)
    start = int(stored.get("region_cursor", 0)) % n
    take = min(count, n)
    selected = [TMDB_REGIONS[(start + i) % n] for i in range(take)]
    next_cursor = (start + take) % n
    return selected, next_cursor


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
    cursors = migrate_cursors(raw.get("scan_cursors"))
    region_cursor_state = raw.get("scan_cursors") or {}

    if len(shows) >= CATALOG_MAX_SIZE:
        print(f"Catalog at cap ({len(shows)}/{CATALOG_MAX_SIZE}); not scanning.")
        return 4

    regions_this_run, next_region_cursor = select_regions_for_run(
        region_cursor_state, TMDB_REGIONS_PER_RUN,
    )

    print(f"Catalog size before: {len(shows)}")
    print(f"Configured regions: {TMDB_REGIONS}; this run: {regions_this_run}")
    for r in regions_this_run:
        c = cursors[r]
        print(f"  cursor[{r}]: tv=p{c['tv']} movie=p{c['movie']}")

    genre_maps = fetch_genre_maps(api_key)
    originals_ids = fetch_originals_ids(api_key)
    print(f"Identified {len(originals_ids)} TV originals on this scan slice.")

    by_tmdb, by_key = index_existing(shows)
    added = 0

    stop_outer = False
    for region in regions_this_run:
        if stop_outer:
            break
        for media in ("tv", "movie"):
            start = max(1, int(cursors[region][media]))
            candidates, last, total = scan_media(
                api_key, media, region, start, TMDB_PAGES_PER_RUN,
                genre_maps[media], originals_ids,
            )
            added_here = 0
            for e in candidates:
                tid = e["tmdb_id"]
                if tid in by_tmdb:
                    continue
                ckey = composite_key(e)
                if ckey in by_key:
                    idx = by_key[ckey]
                    shows[idx].setdefault("tmdb_id", tid)
                    by_tmdb[tid] = idx
                    continue
                shows.append(e)
                by_tmdb[tid] = len(shows) - 1
                by_key[ckey] = len(shows) - 1
                added_here += 1
                added += 1
                if len(shows) >= CATALOG_MAX_SIZE:
                    print(f"Hit CATALOG_MAX_SIZE={CATALOG_MAX_SIZE}; stopping.")
                    stop_outer = True
                    break
            cursors[region][media] = advance_cursor(start, last, total)
            print(f"  [{region} {media}] scanned p{start}..p{last} (total_pages={total}), "
                  f"candidates={len(candidates)}, added={added_here}, next=p{cursors[region][media]}")
            if stop_outer:
                break

    # Availability enrichment: any entry with a tmdb_id but no
    # `available_in` field gets a /watch/providers call so the UI can
    # filter "what's on Netflix in my region". Capped per-run so a huge
    # catalog can't stall a run; remaining entries enrich on the next
    # run.
    enriched = 0
    if MAX_ENRICH_PER_RUN > 0:
        to_enrich = [
            (i, s) for i, s in enumerate(shows)
            if s.get("tmdb_id") and "available_in" not in s
        ][:MAX_ENRICH_PER_RUN]
        if to_enrich:
            print(f"Enriching {len(to_enrich)} entries with watch/providers…")
        for idx, s in to_enrich:
            avail = fetch_availability(api_key, int(s["tmdb_id"]), s.get("type", "movie"))
            if avail is not None:
                shows[idx]["available_in"] = avail
                enriched += 1
            time.sleep(SLEEP_BETWEEN)

    # Persist cursors. Region cursor advances regardless of whether we hit
    # the cap, so a maxed catalog still rotates if we ever raise the cap.
    out_cursors: dict = dict(cursors)
    out_cursors["region_cursor"] = next_region_cursor

    raw["shows"] = [reorder(s) for s in shows]
    raw["scan_cursors"] = out_cursors
    raw["regions"] = TMDB_REGIONS
    raw["source"] = "Catalog discovered via TMDb (Netflix). Ratings from OMDb (IMDb)."
    raw.pop("region", None)  # superseded by regions
    if added > 0 or enriched > 0:
        raw["updated"] = date.today().isoformat()

    DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")

    print()
    print(f"Catalog size after: {len(shows)} (+{added})  enriched: {enriched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
