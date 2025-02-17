import os
import pytest
import requests_mock
from unittest.mock import MagicMock
from src.transactions.pumpportal_transaction import PumpPortalTransaction
from src.models.transaction import Transaction
from src.models.token import Token


@pytest.fixture
def mock_transaction(test_pubkey):
    token = Token(mint=test_pubkey, name="Test Token")
    return Transaction(token=token)


@pytest.fixture
def mock_invalid_transaction():
    token = Token(name="Test Token")
    return Transaction(token=token)


@pytest.fixture
def valid_pumpportal_transaction(mock_transaction):
    return PumpPortalTransaction(mock_transaction)


@pytest.fixture
def invalid_pumpportal_transaction(mock_invalid_transaction):
    return PumpPortalTransaction(mock_invalid_transaction)


class TestPumpPortalTransaction:

    def test_initialization(self, valid_pumpportal_transaction):
        """Test initialization with a valid transaction."""
        assert valid_pumpportal_transaction.token is not None
        assert valid_pumpportal_transaction.token_address is not None

    def test_send_buy_transaction(
        self, valid_pumpportal_transaction
    ):
        """Test buy transaction."""
        valid_pumpportal_transaction.PUMPPORTAL_API_KEY = 'test_api_key'
        with requests_mock.Mocker() as m:
            m.post(
                "https://pumpportal.fun/api/trade?api-key=test_api_key",
                json={"signature": "test_signature"},
            )

            result = valid_pumpportal_transaction.send_buy_transaction(amount=1, slippage=3)
            assert result is True

        with requests_mock.Mocker() as m:
            m.post(
                "https://pumpportal.fun/api/trade?api-key=test_api_key",
                json={"errors": ["Buy failed"]},
            )

            result = valid_pumpportal_transaction.send_buy_transaction(amount=1, slippage=3)
            assert result is False

    def test_send_sell_transaction(
        self, valid_pumpportal_transaction
    ):
        """Test sell transaction."""
        valid_pumpportal_transaction.PUMPPORTAL_API_KEY = 'test_api_key'
        with requests_mock.Mocker() as m:
            m.post(
                "https://pumpportal.fun/api/trade?api-key=test_api_key",
                json={"signature": "test_signature"},
            )

            result = valid_pumpportal_transaction.send_sell_transaction(
                amount=100, slippage=3
            )
            assert result is True

        with requests_mock.Mocker() as m:
            m.post(
                "https://pumpportal.fun/api/trade?api-key=test_api_key",
                json={"errors": ["Sell failed"]},
            )

            result = valid_pumpportal_transaction.send_sell_transaction(
                amount=100, slippage=3
            )
            assert result is False

    def test_send_transaction_missing_api_key(
        self, valid_pumpportal_transaction
    ):
        """Test failure when API key is missing."""
        valid_pumpportal_transaction.PUMPPORTAL_API_KEY = None
        assert (
            valid_pumpportal_transaction.send_buy_transaction(amount=1, slippage=3)
            is False
        )
        assert (
            valid_pumpportal_transaction.send_sell_transaction(amount=100, slippage=3)
            is False
        )

    def test_send_transaction_missing_tokens(
        self, invalid_pumpportal_transaction
    ):
        """Test failure when API key is missing."""
        valid_pumpportal_transaction.PUMPPORTAL_API_KEY = 'test_key'
        assert (
            invalid_pumpportal_transaction.send_buy_transaction(amount=1, slippage=3)
            is False
        )
        assert (
            invalid_pumpportal_transaction.send_sell_transaction(amount=100, slippage=3)
            is False
        )
