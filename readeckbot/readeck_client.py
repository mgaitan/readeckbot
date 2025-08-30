from typing import Any
from io import BytesIO
import subprocess

from .config import READECK_BASE_URL
from . import requests


def get_readeck_version() -> str:
    """
    Returns the version string of the installed readeck binary.
    """
    try:
        result = subprocess.run(["readeck", "version"], capture_output=True, text=True, check=True)
        # Expected output: "readeck version: 0.19.2"
        return result.stdout.strip()
    except Exception as e:
        return f"Could not determine readeck version: {e}"


async def is_admin_user(token: str) -> bool:
    """
    Checks if the user associated with the given token is an admin in Readeck.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
    }
    try:
        resp = await requests.get(f"{READECK_BASE_URL}/api/profile", headers=headers)
        data = await resp.json()
        roles = data.get("provider", {}).get("roles", [])
        return "admin" in roles
    except Exception:
        return False


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

async def favorite_bookmark(bookmark_id: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "content-type": "application/json",
    }
    patch_url = f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}"
    payload = {"is_marked": True}
    response = await requests.patch(patch_url, headers=headers, json=payload)
    response.raise_for_status()
    return True

async def unfavorite_bookmark(bookmark_id: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "content-type": "application/json",
    }
    patch_url = f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}"
    payload = {"is_marked": False}
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
