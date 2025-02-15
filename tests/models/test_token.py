import pytest
from solders.pubkey import Pubkey
from src.models.token import Token


class TestToken:
    """Unit tests for the Token dataclass."""

    def test_token_initialization(self, test_pubkey):
        """Test that a Token instance initializes correctly with provided values."""
        token = Token(mint=test_pubkey, name="Sample Token", symbol="STK")
        assert isinstance(token.mint, Pubkey)
        assert token.name == "Sample Token"
        assert token.symbol == "STK"

    def test_token_default_values(self):
        """Test that Token initializes with default None values if not provided."""
        token = Token()
        assert token.mint is None
        assert token.name is None
        assert token.symbol is None
