import pytest

from src.models.transaction import Transaction
from src.models.token import Token


class TestTransaction:
    """Unit tests for the Transaction dataclass."""

    def test_transaction_initialization(self, test_pubkey):
        """Test that a Transaction instance initializes correctly with provided values."""
        token = Token(mint=test_pubkey, name="Sample Token", symbol="STK")
        transaction = Transaction(
            token=token,
            traderPublicKey="Trader123",
            txType="buy",
            tokenAmount=100.0,
            solAmount=1.5,
            marketCapSol=500.0,
            initialBuy=50.0,
        )

        assert transaction.token == token
        assert transaction.traderPublicKey == "Trader123"
        assert transaction.txType == "buy"
        assert transaction.tokenAmount == 100.0
        assert transaction.solAmount == 1.5
        assert transaction.marketCapSol == 500.0
        assert transaction.initialBuy == 50.0

    def test_transaction_default_values(self):
        """Test that Transaction initializes with default None values if not provided."""
        transaction = Transaction()
        assert transaction.token is None
        assert transaction.traderPublicKey is None
        assert transaction.txType is None
        assert transaction.tokenAmount is None
        assert transaction.solAmount is None
        assert transaction.marketCapSol is None
        assert transaction.initialBuy is None

    def test_token_price_calculation(self):
        """Test that token_price method correctly calculates price per token."""
        transaction = Transaction(txType="buy", tokenAmount=100.0, solAmount=2.0)
        assert transaction.token_price() == 2.0 / 100.0

        transaction_2 = Transaction(txType="create", initialBuy=100.0, solAmount=2.0)
        assert transaction_2.token_price() == 2.0 / 100.0

    def test_token_price_with_zero_amount(self):
        """Test that token_price method returns None if tokenAmount is zero."""
        transaction = Transaction(txType="sell", tokenAmount=0.0, solAmount=2.0)
        assert transaction.token_price() is None

    def test_token_price_with_none_values(self):
        """Test that token_price method returns None if required values are missing."""
        transaction = Transaction(txType="buy", tokenAmount=None, solAmount=2.0)
        assert transaction.token_price() is None

        transaction = Transaction(txType="buy", tokenAmount=100.0, solAmount=None)
        assert transaction.token_price() is None

        transaction = Transaction(txType="buy", tokenAmount=None, solAmount=None)
        assert transaction.token_price() is None
