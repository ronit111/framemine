"""Tests for framemine.dedup module."""

from framemine.dedup import deduplicate, normalize_title


class TestNormalizeTitle:
    def test_normalize_title_lowercase(self):
        assert normalize_title("The Great Gatsby") == "the great gatsby"

    def test_normalize_title_strips_punctuation(self):
        assert normalize_title("Hello, World!") == "hello world"

    def test_normalize_title_collapses_whitespace(self):
        assert normalize_title("hello   world") == "hello world"


class TestDeduplicate:
    def test_deduplicate_removes_exact_dupes(self):
        items = [
            {"title": "Sapiens"},
            {"title": "Sapiens"},
            {"title": "Atomic Habits"},
        ]
        result = deduplicate(items)
        assert len(result) == 2
        assert result[0]["title"] == "Sapiens"
        assert result[1]["title"] == "Atomic Habits"

    def test_deduplicate_removes_normalized_dupes(self):
        items = [
            {"title": "The Great Gatsby"},
            {"title": "the great gatsby"},
        ]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0]["title"] == "The Great Gatsby"

    def test_deduplicate_preserves_order(self):
        items = [
            {"title": "Book A"},
            {"title": "Book B"},
            {"title": "book a"},
            {"title": "Book C"},
        ]
        result = deduplicate(items)
        assert [item["title"] for item in result] == ["Book A", "Book B", "Book C"]

    def test_deduplicate_multi_field_key(self):
        items = [
            {"title": "Dune", "author": "Frank Herbert"},
            {"title": "Dune", "author": "Someone Else"},
            {"title": "Dune", "author": "Frank Herbert"},
        ]
        result = deduplicate(items, key_fields=["title", "author"])
        assert len(result) == 2
        assert result[0]["author"] == "Frank Herbert"
        assert result[1]["author"] == "Someone Else"

    def test_deduplicate_empty_list(self):
        assert deduplicate([]) == []

    def test_deduplicate_no_dupes(self):
        items = [
            {"title": "Book A"},
            {"title": "Book B"},
            {"title": "Book C"},
        ]
        result = deduplicate(items)
        assert len(result) == 3
        assert result == items
