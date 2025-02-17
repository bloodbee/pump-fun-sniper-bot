from copy import deepcopy
from unittest.mock import AsyncMock, patch, MagicMock, call, Mock
import asyncio
import difflib
import json
import os
import pytest

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.rpc.responses import GetLatestBlockhashResp
from solders.system_program import transfer, TransferParams
from solders.transaction import VersionedTransaction

from src.bot import Bot
from src.models.token import Token
from src.models.transaction import Transaction
from src.parser import Parser


class TestBot:

    @classmethod
    def setup_class(cls):
        cls.bot = Bot()

    @pytest.fixture(autouse=True)
    def set_wallet_private_key(self, monkeypatch):
        monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")

    def teardown_method(self):
        # clean tracked tokens
        self.bot.tracked_tokens = {}

    @pytest.mark.asyncio
    async def test_subscribe_new_tokens(self):
        """Test subscribing to new token notifications."""
        ws_mock = AsyncMock()
        await self.bot.subscribe_new_tokens(ws_mock)
        ws_mock.send.assert_called_once_with(
            json.dumps({"method": "subscribeNewToken"})
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_new_tokens(self):
        """Test unsubscribing from new token notifications."""
        ws_mock = AsyncMock()
        await self.bot.unsubscribe_new_tokens(ws_mock)
        ws_mock.send.assert_called_once_with(
            json.dumps({"method": "unsubscribeNewToken"})
        )

    @pytest.mark.asyncio
    async def test_subscribe_token_transactions(self):
        """Test subscribing to token transactions."""
        ws_mock = AsyncMock()
        token_address = "some_token_address"
        await self.bot.subscribe_token_transactions(ws_mock, token_address)
        ws_mock.send.assert_called_once_with(
            json.dumps({"method": "subscribeTokenTrade", "keys": [token_address]})
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_token_transactions(self):
        """Test unsubscribing from token transactions."""
        ws_mock = AsyncMock()
        token_address = "some_token_address"
        await self.bot.unsubscribe_token_transactions(ws_mock, token_address)
        ws_mock.send.assert_called_once_with(
            json.dumps({"method": "unsubscribeTokenTrade", "keys": [token_address]})
        )

    # @pytest.mark.asyncio
    # async def test_send_rpc_buy_transaction(self, test_pubkey, test_account, monkeypatch):
    #     """Test sending a buy transaction."""
    #     token = Token(mint=test_pubkey, name="Test Token")
    #     transaction = Transaction(
    #         token=token, vSolInBondingCurve=100, vTokensInBondingCurve=100
    #     )
    #     transaction.set_associated_bonding_curve()
    #     self.bot.account = test_account

    #     mock_client = AsyncMock(spec=AsyncClient)
    #     mock_client.confirm_transaction.return_value = True
    #     with patch(
    #         "solana.rpc.async_api.AsyncClient", return_value=mock_client
    #     ), patch.object(
    #         self.bot, "_Bot__create_ata", return_value=None
    #     ):
    #         result = await self.bot.send_rpc_buy_transaction(transaction)
    #         assert result is True

    # @pytest.mark.asyncio
    # async def test_send_rpc_buy_transaction_failure(self, test_pubkey, test_account):
    #     """Test sending a buy transaction when it fails."""
    #     token = Token(mint=test_pubkey, name="Test Token")
    #     transaction = Transaction(
    #         token=token, vTokensInBondingCurve=100, vSolInBondingCurve=100
    #     )
    #     transaction.set_associated_bonding_curve()
    #     self.bot.account = test_account

    #     mock_client = AsyncMock(spec=AsyncClient)
    #     mock_client.confirm_transaction.return_value = False
    #     self.bot._Bot__send_transaction = AsyncMock(
    #         side_effect=Exception("Transaction failed")
    #     )
    #     with patch(
    #         "solana.rpc.async_api.AsyncClient", return_value=mock_client
    #     ):
    #         result = await self.bot.send_rpc_buy_transaction(transaction)
    #         assert result is False

    @pytest.mark.asyncio
    async def test_run_create_transaction(self, load_file):
        """Test bot processing a 'create' transaction."""
        message = load_file("tests/etc/transactions/create.json")
        tx = Parser(json.loads(message)).parse()
        token_address = str(tx.token.mint)

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [
            message
        ]  # Simulate WebSocket message streaming

        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_ws

        with patch("websockets.connect", return_value=mock_connect), patch.object(
            self.bot, "subscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "subscribe_token_transactions", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_token_transactions", new_callable=AsyncMock
        ), patch(
            "src.transactions.rpc_transaction.RpcTransaction.send_buy_transaction",
            new_callable=AsyncMock,
            return_value=True,
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            self.bot.subscribe_token_transactions.assert_called_once_with(
                mock_ws, token_address
            )
            self.bot.unsubscribe_new_tokens.assert_called_once_with(mock_ws)

    @pytest.mark.asyncio
    async def test_run_buy_transaction(self, load_file):
        """Test bot processing a 'buy' transaction."""
        message = load_file("tests/etc/transactions/buy.json")
        tx = Parser(json.loads(message)).parse()
        token_address = str(tx.token.mint)

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [
            message
        ]  # Simulate WebSocket message streaming

        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_ws

        self.bot.tracked_tokens[token_address] = tx.token

        with patch("websockets.connect", return_value=mock_connect), patch.object(
            self.bot, "subscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_token_transactions", new_callable=AsyncMock
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            assert self.bot.tracked_tokens[token_address].price == tx.token_price()

    @pytest.mark.asyncio
    async def test_run_sell_transaction(self, load_file):
        """Test bot processing a 'sell' transaction."""
        message = load_file("tests/etc/transactions/sell.json")
        tx = Parser(json.loads(message)).parse()
        token_address = str(tx.token.mint)

        self.bot.tracked_tokens[token_address] = deepcopy(tx.token)
        self.bot.tracked_tokens[token_address].price = 0.008

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [
            message
        ]  # Simulate WebSocket message streaming

        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_ws

        with patch("websockets.connect", return_value=mock_connect), patch.object(
            self.bot, "subscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_token_transactions", new_callable=AsyncMock
        ), patch(
            "src.transactions.rpc_transaction.RpcTransaction.send_sell_transaction",
            new_callable=AsyncMock,
            return_value=True,
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            self.bot.unsubscribe_token_transactions.calls = [
                call(mock_ws, token_address),
                call(mock_ws, token_address),
            ]
            self.bot.unsubscribe_new_tokens.asseunsubscribe_token_transactiort_called_once_with(
                mock_ws
            )
