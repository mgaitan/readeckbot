import pytest
from readeckbot.telegraph.md_to_dom import md_to_dom


@pytest.fixture
def content():
    return """
## Markdown example

- **Bold text:** Use `**text**` to make text **bold**.
- *Italic text:* Use `*text*` or `_text_` to make text *italic*.
- ***Bold and Italic:*** You can combine them with triple asterisks, like ***this example***.
- ~~Strikethrough text:~~ Wrap text in `~~` to get ~~strikethrough~~.

### Mixed Formats in a Sentence

You can combine several formats in one sentence. For example, here is some ***bold and italic text*** alongside `inline code` to emphasize certain elements.

### Links with Code Formatting

It is also possible to have a link whose text is formatted as inline code. For instance: [`Special_Link`](https://www.example.com). This link uses code formatting for its text.

### Additional Inline Formatting

Sometimes you might want to mix more styles:
- **Bold**, _italic_, and `inline code` can all appear in the same sentence.
- Try this: **This is bold**, _this is italic_, and `this is code` all together.

**Final Example:** Check out [**Ultimate_Link**](https://www.example.com/ultimate) which combines bold into one link!

Enjoy testing your parser with this rich variety of inline formatting!
"""


def test_md_to_dom(content):
    assert md_to_dom(content) == [
        {"tag": "h4", "children": ["Markdown example"]},
        {
            "tag": "ul",
            "children": [
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                {"tag": "strong", "children": ["Bold text:"]},
                                " Use ",
                                {"tag": "code", "children": ["**text**"]},
                                " to make text ",
                                {"tag": "strong", "children": ["bold"]},
                                ".",
                            ],
                        }
                    ],
                },
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                {"tag": "em", "children": ["Italic text:"]},
                                " Use ",
                                {"tag": "code", "children": ["*text*"]},
                                " or ",
                                {"tag": "code", "children": ["_text_"]},
                                " to make text ",
                                {"tag": "em", "children": ["italic"]},
                                ".",
                            ],
                        }
                    ],
                },
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                {"tag": "em", "children": [{"tag": "strong", "children": ["Bold and Italic:"]}]},
                                " You can combine them with triple asterisks, like ",
                                {"tag": "em", "children": [{"tag": "strong", "children": ["this example"]}]},
                                ".",
                            ],
                        }
                    ],
                },
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                {"tag": "del", "children": ["Strikethrough text:"]},
                                " Wrap text in ",
                                {"tag": "code", "children": ["~~"]},
                                " to get ~~strikethrough~~.",
                            ],
                        }
                    ],
                },
            ],
        },
        {"tag": "p", "children": [{"tag": "strong", "children": ["Mixed Formats in a Sentence"]}]},
        {
            "tag": "p",
            "children": [
                "You can combine several formats in one sentence. For example, here is some ",
                {"tag": "em", "children": [{"tag": "strong", "children": ["bold and italic text"]}]},
                " alongside ",
                {"tag": "code", "children": ["inline code"]},
                " to emphasize certain elements.",
            ],
        },
        {"tag": "p", "children": [{"tag": "strong", "children": ["Links with Code Formatting"]}]},
        {
            "tag": "p",
            "children": [
                "It is also possible to have a link whose text is formatted as inline code. For instance: ",
                {
                    "tag": "a",
                    "attrs": {"href": "https://www.example.com"},
                    "children": [{"tag": "code", "children": ["Special_Link"]}],
                },
                ". This link uses code formatting for its text.",
            ],
        },
        {"tag": "p", "children": [{"tag": "strong", "children": ["Additional Inline Formatting"]}]},
        {"tag": "p", "children": ["Sometimes you might want to mix more styles:"]},
        {
            "tag": "ul",
            "children": [
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                {"tag": "strong", "children": ["Bold"]},
                                ", ",
                                {"tag": "em", "children": ["italic"]},
                                ", and ",
                                {"tag": "code", "children": ["inline code"]},
                                " can all appear in the same sentence.",
                            ],
                        }
                    ],
                },
                {
                    "tag": "li",
                    "children": [
                        {
                            "tag": "p",
                            "children": [
                                "Try this: ",
                                {"tag": "strong", "children": ["This is bold"]},
                                ", ",
                                {"tag": "em", "children": ["this is italic"]},
                                ", and ",
                                {"tag": "code", "children": ["this is code"]},
                                " all together.",
                            ],
                        }
                    ],
                },
            ],
        },
        {
            "tag": "p",
            "children": [
                {"tag": "strong", "children": ["Final Example:"]},
                " Check out ",
                {
                    "tag": "a",
                    "attrs": {"href": "https://www.example.com/ultimate"},
                    "children": [{"tag": "strong", "children": ["Ultimate_Link"]}],
                },
                " which combines bold into one link!",
            ],
        },
        {"tag": "p", "children": ["Enjoy testing your parser with this rich variety of inline formatting!"]},
    ]
