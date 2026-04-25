"""Shared catalog helpers: identity, normalization, merging.

Single source of truth for what "the same show" means across the
catalog grower (refresh_catalog.py) and the dedupe pass
(dedupe_catalog.py). Don't reimplement these elsewhere.
"""

from __future__ import annotations

import re
import unicodedata

# Priority used when reconciling netflix_status during a merge. Higher
# wins. "original" is the most informative classification, "library" the
# least, so a merge between two duplicates promotes to the most specific
# label any source claimed.
NETFLIX_STATUS_PRIORITY = {
    "original": 3,
    "exclusive-region": 2,
    "library": 1,
}


def normalize_title(s: str | None) -> str:
    """Stable, comparison-safe form of a title.

    Strips accents, lowercases, collapses punctuation/whitespace. Designed
    so trivial differences in source data don't fragment one show into
    multiple catalog entries:

        "Spider-Man: Across the Spider-Verse"
        "Spider-Man Across the Spider-Verse"
        "spider-man across the spider-verse "
        "Élite"  vs  "Elite"

    all collapse to the same key.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    lower = stripped.lower().strip()
    # Replace anything that isn't alphanumeric or whitespace with a space,
    # then collapse runs of whitespace.
    spaced = re.sub(r"[^\w\s]", " ", lower, flags=re.UNICODE)
    return re.sub(r"\s+", " ", spaced).strip()


def composite_key(entry: dict) -> tuple[str, int, str]:
    """The dedupe key used when tmdb_id is unavailable.

    type is part of the key so a movie and series sharing title+year
    don't collapse into one another.
    """
    return (
        normalize_title(entry.get("title")),
        int(entry.get("year") or 0),
        entry.get("type") or "",
    )


def merge_entries(group: list[dict]) -> dict:
    """Reconcile duplicates into one canonical entry.

    Field-by-field rules:
      - title / year / type: take from the entry with tmdb_id, else first.
      - rating, votes: max of non-zero values.
      - genres: union, sorted.
      - netflix_status: highest-priority label seen.
      - imdb_id, tmdb_id: any non-empty.
      - rating_refreshed_at: most recent (ISO-8601 strings sort naturally).
      - other unknown fields: first non-empty value.

    Order of `group` doesn't matter; the function is deterministic for
    a fixed input set.
    """
    if not group:
        raise ValueError("merge_entries got empty group")

    ranked = sorted(
        group,
        key=lambda e: (
            0 if e.get("tmdb_id") else 1,
            0 if e.get("imdb_id") else 1,
            -(e.get("votes") or 0),
            -(e.get("rating") or 0),
        ),
    )
    merged: dict = dict(ranked[0])

    for e in ranked[1:]:
        for k, v in e.items():
            if v in (None, "", [], {}):
                continue

            if k in ("genres", "origin_country", "available_in"):
                merged[k] = sorted(set(merged.get(k) or []) | set(v))
            elif k in ("rating", "votes"):
                if (v or 0) > (merged.get(k) or 0):
                    merged[k] = v
            elif k == "netflix_status":
                cur = NETFLIX_STATUS_PRIORITY.get(merged.get(k, ""), 0)
                new = NETFLIX_STATUS_PRIORITY.get(v, 0)
                if new > cur:
                    merged[k] = v
            elif k == "rating_refreshed_at":
                if v > (merged.get(k) or ""):
                    merged[k] = v
            elif k in ("imdb_id", "tmdb_id", "original_language"):
                if not merged.get(k):
                    merged[k] = v
            else:
                merged.setdefault(k, v)
    return merged
