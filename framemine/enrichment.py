"""Per-schema metadata enrichment via external APIs."""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"
OPENLIBRARY_API = "https://openlibrary.org/search.json"

OPENLIBRARY_SKIP_SUBJECTS = frozenset({
    "fiction", "nonfiction", "non-fiction", "large type books",
    "reading level-grade 11", "reading level-grade 12",
    "accessible book", "protected daisy", "in library",
    "lending library", "internet archive wishlist",
})


def enrich_book(title: str, existing_author: str | None = None) -> dict[str, Any]:
    """
    Look up book metadata. Try Google Books, then Open Library for missing fields.

    Returns {"author": str|None, "genre": str|None}.
    Never raises -- catches all API errors.
    """
    author = existing_author
    genre = None

    # Try Google Books for author and genre
    try:
        params = {"q": f"intitle:{title}", "maxResults": 1}
        resp = requests.get(GOOGLE_BOOKS_API, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("totalItems", 0) > 0:
            info = data["items"][0]["volumeInfo"]
            if not author:
                author = info.get("authors", [None])[0]
            categories = info.get("categories", [])
            if categories:
                genre = categories[0]
    except Exception:
        logger.debug("Google Books lookup failed for '%s'", title)

    # Try Open Library for any still-missing fields
    if not author or not genre:
        try:
            params = {"q": title, "limit": 1, "fields": "title,author_name,subject"}
            resp = requests.get(OPENLIBRARY_API, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("docs"):
                doc = data["docs"][0]
                if not author:
                    author = doc.get("author_name", [None])[0]
                if not genre:
                    subjects = doc.get("subject", [])
                    for s in subjects[:10]:
                        if (
                            len(s) > 3
                            and s.lower() not in OPENLIBRARY_SKIP_SUBJECTS
                            and not s.startswith("nyt:")
                        ):
                            genre = s
                            break
                    if not genre and subjects:
                        genre = subjects[0]
        except Exception:
            logger.debug("Open Library lookup failed for '%s'", title)

    return {"author": author, "genre": genre}


def enrich_items(
    items: list[dict],
    schema_name: str,
    enrichment_config: dict | None = None,
    progress_callback: callable | None = None,
) -> list[dict]:
    """
    Enrich items based on schema type.

    - "books": calls enrich_book() for items with type=="book"
    - Other schemas: no-op

    Modifies items in-place. Adds 0.1s delay every 10 items.
    """
    if schema_name != "books":
        return items

    enriched_count = 0
    for i, item in enumerate(items):
        if item.get("type") != "book":
            continue

        result = enrich_book(
            title=item.get("title", ""),
            existing_author=item.get("author"),
        )

        if result["author"]:
            item["author"] = result["author"]
        if result["genre"]:
            item["genre"] = result["genre"]

        enriched_count += 1

        if progress_callback is not None:
            progress_callback(i + 1, len(items))

        # Rate-limit: 0.1s pause every 10 enriched items
        if enriched_count % 10 == 0:
            time.sleep(0.1)

    logger.info("Enriched %d book(s) out of %d items", enriched_count, len(items))
    return items
