import pytest
from src.utils import Utils

DISCRIMINATOR_DATA = [
    ("global:buy", 16927863322537952870),
    ("global:sell", 12502976635542562355),
    ("global:create", 8576854823835016728),
    ("account:BondingCurve", 6966180631402821399),
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

    @pytest.mark.parametrize("instruction_name, expected", DISCRIMINATOR_DATA)
    def test_caculate_discriminator(self, instruction_name, expected):
        """Test calculate discriminator"""
        result = Utils.calculate_discriminator(instruction_name)
        assert result == expected
