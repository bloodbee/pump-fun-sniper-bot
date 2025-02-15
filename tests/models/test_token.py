import pytest
from src.models.token import Token


class TestToken:
    """Unit tests for the Token dataclass."""

    def test_token_initialization(self):
        """Test that a Token instance initializes correctly with provided values."""
        token = Token(mint="ABC123", name="Sample Token", symbol="STK")
        assert token.mint == "ABC123"
        assert token.name == "Sample Token"
        assert token.symbol == "STK"

    def test_token_default_values(self):
        """Test that Token initializes with default None values if not provided."""
        token = Token()
        assert token.mint is None
        assert token.name is None
        assert token.symbol is None

    def test_token_partial_initialization(self):
        """Test that Token can be initialized with partial values."""
        token = Token(mint="XYZ789")
        assert token.mint == "XYZ789"
        assert token.name is None
        assert token.symbol is None
