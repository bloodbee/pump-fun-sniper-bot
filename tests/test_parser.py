import pytest

from src.parser import Parser
from src.models.token import Token
from src.models.transaction import Transaction


class TestParser:
    """Test suite for the Parser class."""

    def test_parse_token_creation(self, load_json):
        """Test parsing a token creation transaction."""
        data = load_json("tests/etc/transactions/create.json")
        parser = Parser(data)
        transaction = parser.parse()

        assert transaction.txType == "create"
        assert isinstance(transaction.token, Token)
        assert transaction.token.mint == "BXvk2E3EtQ68tJ4nSagj4V6eyphCnZ9qHhzqCGoTpump"
        assert transaction.token.name == "Justice For Kanye"
        assert transaction.token.symbol == "JFK"
        assert transaction.solAmount == 2.0
        assert transaction.marketCapSol == 31.81

    def test_parse_buy_transaction(self, load_json):
        """Test parsing a buy transaction."""
        data = load_json("tests/etc/transactions/buy.json")
        parser = Parser(data)
        transaction = parser.parse()

        assert transaction.txType == "buy"
        assert isinstance(transaction.token, Token)
        assert transaction.token.mint == "5D75Q7cxdEZHoYrctCzNJ5nvNSTTm6nGuhUDWgHNpump"
        assert transaction.traderPublicKey == "GSW8ChaXzobBpgxHmm9nmeaRpPyjSj4YnkmgBMzLNbut"
        assert transaction.tokenAmount == 40816.32653
        assert transaction.solAmount == 0.010050302
        assert transaction.marketCapSol == 246.26

    def test_parse_sell_transaction(self, load_json):
        """Test parsing a sell transaction."""
        data = load_json("tests/etc/transactions/sell.json")
        parser = Parser(data)
        transaction = parser.parse()

        assert transaction.txType == "sell"
        assert isinstance(transaction.token, Token)
        assert transaction.token.mint == "5D75Q7cxdEZHoYrctCzNJ5nvNSTTm6nGuhUDWgHNpump"
        assert transaction.traderPublicKey == "GSW8ChaXzobBpgxHmm9nmeaRpPyjSj4YnkmgBMzLNbut"
        assert transaction.tokenAmount == 15000.0
        assert transaction.solAmount == 0.005
        assert transaction.marketCapSol == 120.75
