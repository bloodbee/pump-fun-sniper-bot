import pytest
from src.utils import Utils


EXTRACT_PRICE_DATA = [
    (
        {"result": {"value": ["Some log data...", "Price: 0.1234 SOL", "More data"]}},
        0.1234,
    ),
    (
        {"result": {"value": ["Random log", "Price: 2.5 SOL"]}},
        2.5,
    ),
    (
        {"result": {"value": ["Some random log message"]}},
        0,
    ),
    (
        {"result": {"value": []}},
        0,
    ),
    (
        {},
        0,
    ),
    (
        {"result": {}},
        0,
    ),
    (
        {"result": {"value": ["Price SOL 0.1234"]}},  # Wrong order
        0,
    ),
]


class TestUtils:

    def test_is_similar_token(self, mock_token_storage):
        """Test is similar token"""
        # the token is completely different and should not be skipped.
        result = Utils.is_similar_token(mock_token_storage, "Bitcoin Revolution")
        assert result is False

        # the new token is too similar and should be skipped.
        result = Utils.is_similar_token(mock_token_storage, "Trump for the win")
        assert result is True
        result = Utils.is_similar_token(mock_token_storage, "Trump New Era")
        assert result is True

        # the similarity is below the threshold and should not be skipped.
        result = Utils.is_similar_token(mock_token_storage, "D.O.G.E")
        assert result is False

        # the token storage is empty, it should never be skipped.
        result = Utils.is_similar_token([], "Random New Token")
        assert result is False
