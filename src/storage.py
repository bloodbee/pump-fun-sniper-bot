import os
import json


class Storage:

    TOKEN_STORAGE_FILE = os.getenv("TOKEN_STORAGE_FILE", "token_storage.json")

    def __init__(self, filepath=TOKEN_STORAGE_FILE):
        self.tokens = []
        self.filepath = filepath

    def load(self):
        """Loads purchased tokens from a JSON file."""
        if os.path.exists(self.filepath):
            with open(self.filepath, "r") as file:
                try:
                    self.tokens = json.load(file)
                except json.JSONDecodeError:
                    print("[ERROR] Corrupted token storage file, resetting data.")
                    self.tokens = []  # Reset tokens if the file is corrupted
        else:
            self.tokens = []

    def save(self):
        """Saves purchased tokens to a JSON file."""
        with open(self.filepath, "w") as file:
            json.dump(self.tokens, file, indent=4)
