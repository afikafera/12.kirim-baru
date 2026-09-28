import pytest

from hermes_agent.orchestrator import HermesAgent


@pytest.mark.parametrize("quote", ["”", "’", "“", "‘"])
def test_extract_urls_strips_trailing_smart_quotes(quote):
    assert HermesAgent._extract_urls(
        f"https://example.test/path{quote}"
    ) == ["https://example.test/path"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "https://example.test/O'Reilly",
            ["https://example.test/O'Reilly"],
        ),
        (
            "https://example.test/a(b)",
            ["https://example.test/a(b)"],
        ),
        (
            "https://example.test/a(b));",
            ["https://example.test/a(b)"],
        ),
        (
            "https://example.test/search?q=weather&lang=en",
            ["https://example.test/search?q=weather&lang=en"],
        ),
        (
            "https://example.test/path/",
            ["https://example.test/path/"],
        ),
    ],
)
def test_extract_urls_preserves_valid_url_content_and_suffixes(text, expected):
    assert HermesAgent._extract_urls(text) == expected
