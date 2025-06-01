from typing import Any
from io import BytesIO

from .config import READECK_BASE_URL
from . import requests


async def fetch_bookmarks(
    token: str,
    author: str | None = None,
    is_archived: bool | None = None,
    search: str | None = None,
    site: str | None = None,
    title: str | None = None,
    type_: list[str] | None = None,
    labels: str | None = None,
    is_loaded: bool | None = None,
    has_errors: bool | None = None,
    has_labels: bool | None = None,
    is_marked: bool | None = None,
    range_start: str | None = None,
    range_end: str | None = None,
    read_status: list[str] | None = None,
    updated_since: str | None = None,
    bookmark_id: str | None = None,
    collection: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: list[str] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
    }

    # Prepare query parameters, skipping any that are None
    params = {
        "author": author,
        "is_archived": is_archived,
        "search": search,
        "site": site,
        "title": title,
        "type": type_,
        "labels": labels,
        "is_loaded": is_loaded,
        "has_errors": has_errors,
        "has_labels": has_labels,
        "is_marked": is_marked,
        "range_start": range_start,
        "range_end": range_end,
        "read_status": read_status,
        "updated_since": updated_since,
        "id": bookmark_id,
        "collection": collection,
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }

    # Remove keys with None values
    filtered_params = {k: v for k, v in params.items() if v is not None}

    response = await requests.get(
        f"{READECK_BASE_URL}/api/bookmarks",
        headers=headers,
        params=filtered_params,
    )
    response.raise_for_status()
    return response.json()


async def fetch_article_epub(bookmark_id: str, token: str):
    """Fetch the markdown of a bookmark by its ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "text/epub+zip",
    }
    r = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.epub", headers=headers)
    r.raise_for_status()
    return BytesIO(r.content)


async def save_bookmark(url: str, token: str):
    """Save a bookmark to Readeck and return a link and the bookmark_id."""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "content-type": "application/json",
    }

    r = await requests.post(f"{READECK_BASE_URL}/api/bookmarks", json={"url": url}, headers=headers)
    r.raise_for_status()
    return r.headers.get("Bookmark-Id")


async def archive_bookmark(bookmark_id: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "content-type": "application/json",
    }
    patch_url = f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}"
    payload = {"is_archived": True}
    response = await requests.patch(patch_url, headers=headers, json=payload)
    response.raise_for_status()
    return True


async def fetch_article_markdown(bookmark_id: str, token: str):
    """Fetch the markdown of a bookmark by its ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "text/markdown",
    }
    r = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.md", headers=headers)
    r.raise_for_status()
    return r.text
