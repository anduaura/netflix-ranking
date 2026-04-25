#!/usr/bin/env python3
"""One-shot dedupe pass over shows.json.

Detects duplicates by:
  1. tmdb_id collision (always merged — same TMDb entity).
  2. composite key collision: (normalized_title, year, type)
     across entries with no tmdb_id, or where one tmdb_id is missing.

When two entries share a composite key but BOTH have tmdb_ids and the
ids differ, they are flagged as a CONFLICT and *not* auto-merged. That
combination is rare and usually means TMDb has duplicate listings or
two genuinely different works share a title+year+type — manual review
is safer than silently picking one.

Usage:
    python3 scripts/dedupe_catalog.py            # write changes
    python3 scripts/dedupe_catalog.py --dry-run  # preview only

Exit codes:
  0  done (catalog possibly merged)
  1  unresolved conflicts present (still wrote safe merges)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _catalog import composite_key, merge_entries  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "shows.json"

FIELD_ORDER = [
    "title", "year", "rating", "votes",
    "genres", "type", "netflix_status",
    "original_language", "origin_country", "available_in",
    "imdb_id", "tmdb_id", "rating_refreshed_at",
]


def reorder(entry: dict) -> "OrderedDict[str, object]":
    out: "OrderedDict[str, object]" = OrderedDict()
    for k in FIELD_ORDER:
        if k in entry:
            out[k] = entry[k]
    for k, v in entry.items():
        if k not in out:
            out[k] = v
    return out


def find_duplicates(shows: list[dict]) -> tuple[list[list[int]], list[list[int]]]:
    """Return (mergeable_groups, conflict_groups) as lists of index lists.

    A group is a set of entries we believe describe the same show. A group
    is *mergeable* when at most one tmdb_id is present (or all present ids
    are identical); otherwise it's a *conflict* and left untouched.
    """
    by_tmdb: dict[int, list[int]] = defaultdict(list)
    by_ckey: dict[tuple, list[int]] = defaultdict(list)
    for i, s in enumerate(shows):
        if s.get("tmdb_id"):
            by_tmdb[int(s["tmdb_id"])].append(i)
        by_ckey[composite_key(s)].append(i)

    # Union-find over "same as" relations: same tmdb_id OR same ckey.
    parent = list(range(len(shows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for ids in by_tmdb.values():
        for j in ids[1:]:
            union(ids[0], j)
    for ids in by_ckey.values():
        # Skip empty/zero composite keys — they're degenerate (missing data).
        if not ids:
            continue
        first = shows[ids[0]]
        if not composite_key(first)[0]:  # empty normalized title
            continue
        for j in ids[1:]:
            union(ids[0], j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(shows)):
        groups[find(i)].append(i)

    mergeable: list[list[int]] = []
    conflicts: list[list[int]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ids = {int(shows[i]["tmdb_id"]) for i in members if shows[i].get("tmdb_id")}
        if len(ids) > 1:
            conflicts.append(members)
        else:
            mergeable.append(members)
    return mergeable, conflicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report only; don't write")
    args = parser.parse_args()

    raw = json.loads(DATA_FILE.read_text())
    shows: list[dict] = raw["shows"]
    print(f"Catalog size: {len(shows)}")

    mergeable, conflicts = find_duplicates(shows)
    print(f"Mergeable groups: {len(mergeable)}")
    print(f"Conflict groups:  {len(conflicts)}  (different tmdb_ids, same composite key)")

    for g in mergeable:
        members = [shows[i] for i in g]
        titles = " | ".join(f'{s["title"]} ({s.get("year","?")})' for s in members)
        print(f"  merge: {titles}")

    for g in conflicts:
        members = [shows[i] for i in g]
        titles = " | ".join(
            f'{s["title"]} ({s.get("year","?")}) tmdb={s.get("tmdb_id","?")}'
            for s in members
        )
        print(f"  CONFLICT: {titles}", file=sys.stderr)

    if not mergeable:
        print("No mergeable duplicates found.")
        return 1 if conflicts else 0

    if args.dry_run:
        print("\n(dry-run — not writing changes)")
        return 1 if conflicts else 0

    # Apply merges. Build a new shows list preserving original order: the
    # merged entry takes the slot of the earliest member; later members are
    # dropped.
    drop = set()
    for g in mergeable:
        members = sorted(g)
        target = members[0]
        merged = merge_entries([shows[i] for i in members])
        shows[target] = merged
        for j in members[1:]:
            drop.add(j)

    new_shows = [reorder(s) for i, s in enumerate(shows) if i not in drop]
    raw["shows"] = new_shows
    raw["updated"] = date.today().isoformat()

    DATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    print(f"\nMerged {len(drop)} duplicate entries. New catalog size: {len(new_shows)}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
