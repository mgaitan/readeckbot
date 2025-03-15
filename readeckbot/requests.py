import httpx


async def fetch(method: str, url: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response


async def get(url: str, **kwargs) -> httpx.Response:
    return await fetch("GET", url, **kwargs)


async def post(url: str, **kwargs) -> httpx.Response:
    return await fetch("POST", url, **kwargs)


async def patch(url: str, **kwargs) -> httpx.Response:
    return await fetch("PATCH", url, **kwargs)
