import pytest
from readeckbot.helpers import chunker

@pytest.mark.parametrize(
    "text,limit",
    [
        ("This is a simple sentence.", 100),
        ("Hello world.", 20),
        ("No periods in this text", 50),
    ]
)
def test_chunker_single_chunk(text, limit):
    assert chunker(text, limit) == [text.strip()]

@pytest.mark.parametrize(
    "text,limit,expected",
    [
        (
            "Alice went to the store. She bought apples. Then she went home.",
            30,
            ["Alice went to the store.", "She bought apples.", "Then she went home."]
        ),
        (
            "First. Second. Third.",
            8,
            ["First.", "Second.", "Third."]
        ),
        (
            "Hi. Bye. Yes. No. Ok.",
            5,
            ["Hi.", "Bye.", "Yes.", "No.", "Ok."]
        ),
    ]
)
def test_chunker_split_on_period(text, limit, expected):
    assert chunker(text, limit) == [s.strip() for s in expected]

@pytest.mark.parametrize(
    "text,limit",
    [
        ("No periods here at all", 10),
        ("Another example without punctuation", 15),
    ]
)
def test_chunker_no_periods(text, limit):
    assert chunker(text, limit) == [text.strip()]

def test_chunker_empty_string():
    assert chunker("") == []

def test_chunker_multi_sentence_chunks():
    text = (
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump! "
        "Bright vixens jump; dozy fowl quack."
    )
    expected = [
        "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.",
        "How vexingly quick daft zebras jump! Bright vixens jump; dozy fowl quack."
    ]
    assert chunker(text, 90) == expected

def test_chunker_trailing_spaces():
    text = "First sentence.  Second sentence.   Third sentence. "
    expected = ["First sentence.", "Second sentence.", "Third sentence."]
    assert chunker(text, 20) == expected
