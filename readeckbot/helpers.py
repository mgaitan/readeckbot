from pathlib import Path

from urllib.parse import urlparse

import re
import json


def chunker(article_text: str, limit: int = 4000) -> list[str]:
    """
    Split the article text into chunks of `limit` characters, taking the last dot as limit
    """
    if len(article_text) <= limit:
        stripped = article_text.strip()
        return [stripped] if stripped else []

    chunks = []
    start = 0
    text_len = len(article_text)

    while start < text_len:
        # Set end limit for this chunk
        end = min(start + limit, text_len)

        # Look for the last dot in the range start:end
        last_dot = article_text.rfind(".", start, end)

        if last_dot == -1 or last_dot <= start:
            # No dot found in range; extend to next dot after limit
            next_dot = article_text.find(".", end)
            if next_dot == -1:
                # No more dots at all; just take the rest
                chunks.append(article_text[start:].strip())
                break
            else:
                chunks.append(article_text[start : next_dot + 1].strip())
                start = next_dot + 1
        else:
            chunks.append(article_text[start : last_dot + 1].strip())
            start = last_dot + 1

    return [c.strip() for c in chunks if c.strip()]


class PersistentDict(dict):
    """
    A simple persistent dictionary stored as JSON using pathlib.
    Automatically saves on each set or delete operation.
    """

    def __init__(self, filename: str):
        super().__init__()
        self.path = Path(filename)
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self.update(data)
            except Exception:
                pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self, indent=2))


def escape_markdown_v2(text: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", text)


async def extract_url_title_labels(text: str):
    """Extract URL, title, and labels from text."""
    url_pattern = r"(https?://[^\s]+)"
    match = re.search(url_pattern, text)
    if not match:
        return None, None, []
    url = match.group(0)
    after_url = text.replace(url, "").strip()
    labels = re.findall(r"\+(\w+)", after_url)
    for lbl in labels:
        after_url = after_url.replace(f"+{lbl}", "")
    title = after_url.strip()
    return url, (title if title else None), labels


def normalize_url(url: str) -> str:
    """
    Guarantee that the URL starts with a scheme and
    remove trailing punctuation such as commas or periods.
    """
    url = url.strip(".,:;!?)]}")
    if not urlparse(url).scheme:
        url = f"https://{url}"
    return url


def parse_markdown(markdown: str) -> dict[str, str]:
    """
    Parses a markdown string containing metadata and content.
    with key-value pairs.  For example:

    ---
    title: My Article Title
    save: 2023-10-27
    ---

    The rest of the string is considered the content.
    """
    metadata = {}
    content = ""

    # Split the markdown into metadata and content sections
    parts = markdown.split("---")
    if len(parts) >= 3:
        metadata_str = parts[1].strip()
        content = "---".join(parts[2:]).strip()

        # Parse the metadata string into a dictionary
        for line in metadata_str.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("'").strip('"')
    else:
        content = markdown.strip()

    return {"metadata": metadata, "content": content}
