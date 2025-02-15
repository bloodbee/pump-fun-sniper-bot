import pytest
import os
import json

from src.storage import Storage

class TestStorage:

    @pytest.fixture(autouse=True)
    def setup_storage(self, tmp_path):
        """Fixture to initialize Storage with a temporary file for each test."""
        temp_file = tmp_path / "token_storage.json"
        self.storage = Storage(filepath=str(temp_file))
        self.temp_file = temp_file

    def test_init(self):
        """Test Storage initialization with default and custom file paths."""
        assert self.storage.filepath == str(self.temp_file)
        assert self.storage.tokens == []

    def test_storage_load(self):
        """Test loading from an empty file should return an empty list."""
        # empty file
        self.temp_file.write_text(json.dumps([]))
        self.storage.load()
        assert self.storage.tokens == []

        # existing data
        test_data = [{"name": "TokenA", "address": "abc123"}, {"name": "TokenB", "address": "xyz456"}]
        self.temp_file.write_text(json.dumps(test_data))

        self.storage.load()
        assert self.storage.tokens == test_data

        # missing file
        if self.temp_file.exists():
            self.temp_file.unlink()

        self.storage.load()
        assert self.storage.tokens == []  # Should default to an empty list

        # corrupted file
        self.temp_file.write_text("INVALID_JSON")

        try:
            self.storage.load()
            assert self.storage.tokens == []
        except Exception as e:
            pytest.fail(f"Storage.load() raised an exception: {e}")

    def test_storage_save(self):
        """Test saving tokens to a file."""
        test_data = [{"name": "TokenC", "address": "def789"}]
        self.storage.tokens = test_data
        self.storage.save()

        # read back the file
        with open(self.temp_file, "r") as file:
            saved_data = json.load(file)

        assert saved_data == test_data
        