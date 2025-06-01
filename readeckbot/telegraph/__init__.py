from readeckbot.config import USER_TELEGRAPH
from readeckbot.helpers import parse_markdown
from ytelegraph import TelegraphAPI
from .md_to_dom import md_to_dom


async def get_telegraph_client(effective_user) -> TelegraphAPI:
    user_id = str(effective_user.id)
    telegraph_account = USER_TELEGRAPH.get(user_id)
    if telegraph_account:
        telegraph_token = telegraph_account.get("access_token")
        ph = TelegraphAPI(telegraph_token)
    else:
        telegram_user = effective_user.username or user_id
        ph = TelegraphAPI(
            short_name=f"@{telegram_user}'s readeckbot blog",
            author_name=f"@{telegram_user}",
            author_url=f"https://t.me/{telegram_user}",
        )
        telegraph_token = ph.account.access_token
        USER_TELEGRAPH[user_id] = {
            "access_token": telegraph_token,
            "author_name": telegram_user,
        }
    return ph


async def create_page(effective_user, raw_content: str) -> str:
    # Convert the markdown to a Telegraph-compatible DOM
    md_parsed = parse_markdown(raw_content)
    content = md_parsed["content"]
    title = md_parsed["metadata"]["title"]
    ph = await get_telegraph_client(effective_user)

    dom = md_to_dom(content)
    # Optionally remove the first node if it redundantly contains the title
    if dom and title in dom[0]["children"]:
        dom = dom[1:]
    # Publish the markdown as a Telegraph page.
    page_link = ph.create_page(title, dom)
    return page_link
