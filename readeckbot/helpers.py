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
        last_dot = article_text.rfind('.', start, end)

        if last_dot == -1 or last_dot <= start:
            # No dot found in range; extend to next dot after limit
            next_dot = article_text.find('.', end)
            if next_dot == -1:
                # No more dots at all; just take the rest
                chunks.append(article_text[start:].strip())
                break
            else:
                chunks.append(article_text[start:next_dot + 1].strip())
                start = next_dot + 1
        else:
            chunks.append(article_text[start:last_dot + 1].strip())
            start = last_dot + 1

    return [c.strip() for c in chunks if c.strip()]
