import difflib
import os
import re

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))
FREEZE_AUTHORITY_REVOKED = os.getenv("ALLOW_FREEZE_AUTHORITY_REVOKED", True)
MINT_AUTHORITY_REVOKED = os.getenv("ALLOW_MINT_AUTHORITY_REVOKED", True)


class Utils:

    @staticmethod
    def is_similar_token(tokens, new_token_name):
        """Checks if a token's name is too similar to a previously bought token."""
        for token in tokens:
            existing_name = token["name"]
            similarity = difflib.SequenceMatcher(
                None, existing_name.lower(), new_token_name.lower()
            ).ratio()

            if similarity >= SIMILARITY_THRESHOLD:
                print(
                    f"[SKIPPED] {new_token_name} (Too similar to {existing_name}, Similarity: {similarity:.2f})"  # noqa: E501
                )
                return True
        return False
