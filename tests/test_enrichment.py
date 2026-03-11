"""Tests for framemine.enrichment module."""

from unittest.mock import MagicMock, patch

from framemine.enrichment import enrich_book, enrich_items


class TestEnrichBook:
    @patch("framemine.enrichment.requests.get")
    def test_enrich_book_google_books_success(self, mock_get):
        """Google Books returns author + categories."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "totalItems": 1,
            "items": [{
                "volumeInfo": {
                    "authors": ["F. Scott Fitzgerald"],
                    "categories": ["Fiction"],
                }
            }],
        }
        mock_get.return_value = mock_response

        result = enrich_book("The Great Gatsby")
        assert result["author"] == "F. Scott Fitzgerald"
        assert result["genre"] == "Fiction"

    @patch("framemine.enrichment.requests.get")
    def test_enrich_book_google_books_no_results_falls_back_to_openlibrary(self, mock_get):
        """Google returns 0 results, Open Library returns data."""
        google_response = MagicMock()
        google_response.raise_for_status = MagicMock()
        google_response.json.return_value = {"totalItems": 0}

        ol_response = MagicMock()
        ol_response.raise_for_status = MagicMock()
        ol_response.json.return_value = {
            "docs": [{
                "author_name": ["Harper Lee"],
                "subject": ["American Literature", "fiction", "Classic"],
            }]
        }

        mock_get.side_effect = [google_response, ol_response]

        result = enrich_book("To Kill a Mockingbird")
        assert result["author"] == "Harper Lee"
        assert result["genre"] == "American Literature"

    @patch("framemine.enrichment.requests.get")
    def test_enrich_book_both_apis_fail(self, mock_get):
        """Both APIs raise exceptions, returns None for both fields."""
        mock_get.side_effect = Exception("Network error")

        result = enrich_book("Some Book")
        assert result["author"] is None
        assert result["genre"] is None

    @patch("framemine.enrichment.requests.get")
    def test_enrich_book_skips_bad_openlibrary_subjects(self, mock_get):
        """Filters out low-value subjects like 'accessible book'."""
        google_response = MagicMock()
        google_response.raise_for_status = MagicMock()
        google_response.json.return_value = {"totalItems": 0}

        ol_response = MagicMock()
        ol_response.raise_for_status = MagicMock()
        ol_response.json.return_value = {
            "docs": [{
                "author_name": ["Test Author"],
                "subject": [
                    "accessible book",
                    "protected daisy",
                    "in library",
                    "lending library",
                    "nyt:fiction",
                    "Historical Fiction",
                ],
            }]
        }

        mock_get.side_effect = [google_response, ol_response]

        result = enrich_book("Test Book")
        assert result["genre"] == "Historical Fiction"


class TestEnrichItems:
    @patch("framemine.enrichment.enrich_book")
    def test_enrich_items_books_schema(self, mock_enrich_book):
        """Only enriches items with type=='book'."""
        mock_enrich_book.return_value = {"author": "Author X", "genre": "Sci-Fi"}

        items = [
            {"title": "Book One", "type": "book", "author": None},
            {"title": "Podcast One", "type": "podcast"},
            {"title": "Book Two", "type": "book", "author": "Existing"},
        ]

        result = enrich_items(items, schema_name="books")

        assert result[0]["author"] == "Author X"
        assert result[0]["genre"] == "Sci-Fi"
        assert "genre" not in result[1]  # podcast untouched
        assert result[2]["author"] == "Author X"
        assert mock_enrich_book.call_count == 2

    @patch("framemine.enrichment.enrich_book")
    def test_enrich_items_other_schema_noop(self, mock_enrich_book):
        """Non-books schema returns items unchanged."""
        items = [{"title": "Recipe", "type": "recipe"}]
        result = enrich_items(items, schema_name="recipes")

        assert result == items
        mock_enrich_book.assert_not_called()

    @patch("framemine.enrichment.enrich_book")
    def test_enrich_items_calls_progress_callback(self, mock_enrich_book):
        """Progress callback is invoked for each book item."""
        mock_enrich_book.return_value = {"author": "A", "genre": "G"}
        callback = MagicMock()

        items = [
            {"title": "Book 1", "type": "book"},
            {"title": "Book 2", "type": "book"},
        ]

        enrich_items(items, schema_name="books", progress_callback=callback)

        assert callback.call_count == 2
        callback.assert_any_call(1, 2)
        callback.assert_any_call(2, 2)
