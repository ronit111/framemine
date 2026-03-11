"""Tests for the schema loading system."""

import pytest
from pathlib import Path

from framemine.schema import Schema, list_schemas, load_schema, get_schema_info, SCHEMAS_DIR


class TestListSchemas:
    def test_list_schemas(self):
        """Returns at least the three built-in schemas."""
        schemas = list_schemas()
        assert "books" in schemas
        assert "products" in schemas
        assert "recipes" in schemas

    def test_list_schemas_sorted(self):
        """Schema names are returned in sorted order."""
        schemas = list_schemas()
        assert schemas == sorted(schemas)


class TestLoadBooksSchema:
    def test_load_books_schema(self):
        """Books schema loads with all fields populated correctly."""
        schema = load_schema("books")
        assert schema.name == "books"
        assert schema.display_name == "Books & Reading"
        assert schema.description == "Extract book, essay, article, and newsletter recommendations"
        assert schema.output_columns == ["title", "author", "type", "genre", "source"]
        assert schema.dedup_key == ["title"]
        assert schema.enrichment == "books"
        assert schema.item_type_field == "type"

    def test_books_prompt_contains_json_format(self):
        """Books prompt includes the expected JSON output format."""
        schema = load_schema("books")
        assert '"title"' in schema.prompt
        assert '"author"' in schema.prompt
        assert "book|essay|article|newsletter|other" in schema.prompt


class TestLoadRecipesSchema:
    def test_load_recipes_schema(self):
        """Recipes schema loads with all fields populated correctly."""
        schema = load_schema("recipes")
        assert schema.name == "recipes"
        assert schema.display_name == "Recipes & Cooking"
        assert "recipe" in schema.description.lower()
        assert "name" in schema.output_columns
        assert "cuisine" in schema.output_columns
        assert "difficulty" in schema.output_columns
        assert "key_ingredients" in schema.output_columns
        assert schema.dedup_key == ["name"]
        assert schema.enrichment is None
        assert schema.item_type_field is None

    def test_recipes_prompt_handles_video_and_cards(self):
        """Recipes prompt mentions recipe cards and video frames."""
        schema = load_schema("recipes")
        assert "recipe card" in schema.prompt.lower() or "recipe cards" in schema.prompt.lower()
        assert "video" in schema.prompt.lower()


class TestLoadProductsSchema:
    def test_load_products_schema(self):
        """Products schema loads with all fields populated correctly."""
        schema = load_schema("products")
        assert schema.name == "products"
        assert schema.display_name == "Product Recommendations"
        assert "product" in schema.description.lower()
        assert "name" in schema.output_columns
        assert "brand" in schema.output_columns
        assert "category" in schema.output_columns
        assert "price_range" in schema.output_columns
        assert schema.dedup_key == ["name", "brand"]
        assert schema.enrichment is None
        assert schema.item_type_field is None

    def test_products_prompt_handles_hauls_and_unboxing(self):
        """Products prompt mentions hauls and unboxing."""
        schema = load_schema("products")
        prompt_lower = schema.prompt.lower()
        assert "unboxing" in prompt_lower
        assert "haul" in prompt_lower


class TestLoadNonexistentSchema:
    def test_load_nonexistent_schema(self):
        """Loading a missing schema raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not_a_real_schema"):
            load_schema("not_a_real_schema")


class TestAllSchemasValid:
    @pytest.fixture
    def all_schema_names(self):
        return list_schemas()

    def test_schema_prompt_not_empty(self, all_schema_names):
        """All schemas have non-empty prompts."""
        for name in all_schema_names:
            schema = load_schema(name)
            assert schema.prompt.strip(), f"Schema '{name}' has an empty prompt"

    def test_schema_output_columns_not_empty(self, all_schema_names):
        """All schemas have non-empty output_columns."""
        for name in all_schema_names:
            schema = load_schema(name)
            assert len(schema.output_columns) > 0, f"Schema '{name}' has no output_columns"

    def test_schema_dedup_key_not_empty(self, all_schema_names):
        """All schemas have non-empty dedup_key."""
        for name in all_schema_names:
            schema = load_schema(name)
            assert len(schema.dedup_key) > 0, f"Schema '{name}' has no dedup_key"

    def test_dedup_key_subset_of_columns(self, all_schema_names):
        """All dedup_key fields should be present in output_columns."""
        for name in all_schema_names:
            schema = load_schema(name)
            for key in schema.dedup_key:
                assert key in schema.output_columns, (
                    f"Schema '{name}': dedup_key '{key}' not in output_columns"
                )


class TestGetSchemaInfo:
    def test_get_schema_info(self):
        """Returns correct structure for all schemas."""
        info = get_schema_info()
        assert isinstance(info, list)
        assert len(info) >= 3

        names = {entry["name"] for entry in info}
        assert "books" in names
        assert "products" in names
        assert "recipes" in names

        for entry in info:
            assert "name" in entry
            assert "display_name" in entry
            assert "description" in entry
            assert len(entry) == 3

    def test_get_schema_info_matches_loaded(self):
        """Info entries match the actual loaded schema data."""
        for entry in get_schema_info():
            schema = load_schema(entry["name"])
            assert entry["display_name"] == schema.display_name
            assert entry["description"] == schema.description


class TestSchemaYAMLValidation:
    def test_malformed_yaml(self, tmp_path, monkeypatch):
        """Malformed YAML raises ValueError."""
        bad_yaml = tmp_path / "broken.yaml"
        bad_yaml.write_text(": : : not valid yaml\n  - [\n")
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        with pytest.raises(ValueError, match="Malformed YAML"):
            load_schema("broken")

    def test_missing_required_fields(self, tmp_path, monkeypatch):
        """YAML missing required fields raises ValueError."""
        incomplete = tmp_path / "incomplete.yaml"
        incomplete.write_text("name: incomplete\ndisplay_name: Test\n")
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        with pytest.raises(ValueError, match="missing required fields"):
            load_schema("incomplete")

    def test_non_mapping_yaml(self, tmp_path, monkeypatch):
        """YAML that parses as a list instead of a mapping raises ValueError."""
        list_yaml = tmp_path / "listfile.yaml"
        list_yaml.write_text("- item1\n- item2\n")
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_schema("listfile")

    def test_empty_prompt(self, tmp_path, monkeypatch):
        """Schema with empty prompt raises ValueError."""
        bad_schema = tmp_path / "emptyprompt.yaml"
        bad_schema.write_text(
            'name: emptyprompt\n'
            'display_name: "Empty"\n'
            'description: "Test"\n'
            'prompt: ""\n'
            'output_columns: ["a"]\n'
            'dedup_key: ["a"]\n'
        )
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        with pytest.raises(ValueError, match="prompt must be a non-empty string"):
            load_schema("emptyprompt")

    def test_empty_output_columns(self, tmp_path, monkeypatch):
        """Schema with empty output_columns raises ValueError."""
        bad_schema = tmp_path / "nocols.yaml"
        bad_schema.write_text(
            'name: nocols\n'
            'display_name: "No Cols"\n'
            'description: "Test"\n'
            'prompt: "Do something"\n'
            'output_columns: []\n'
            'dedup_key: ["a"]\n'
        )
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        with pytest.raises(ValueError, match="output_columns must be a non-empty list"):
            load_schema("nocols")

    def test_valid_custom_schema(self, tmp_path, monkeypatch):
        """A well-formed custom YAML loads successfully."""
        good = tmp_path / "custom.yaml"
        good.write_text(
            'name: custom\n'
            'display_name: "Custom Schema"\n'
            'description: "A test schema"\n'
            'prompt: "Extract things"\n'
            'output_columns: ["field_a", "field_b"]\n'
            'dedup_key: ["field_a"]\n'
        )
        monkeypatch.setattr("framemine.schema.SCHEMAS_DIR", tmp_path)

        schema = load_schema("custom")
        assert schema.name == "custom"
        assert schema.enrichment is None
        assert schema.item_type_field is None
