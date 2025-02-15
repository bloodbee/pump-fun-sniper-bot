import json
import os
import pytest
import requests
import difflib
from copy import deepcopy
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, call
import requests_mock

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.message import Message
from solders.transaction import VersionedTransaction
from solders.system_program import transfer, TransferParams
from solders.rpc.responses import GetLatestBlockhashResp
from solders.hash import Hash

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

    @pytest.mark.asyncio
    async def test_send_buy_transaction(self, test_account):
        """Test sending a buy transaction."""
        token = Token(
            mint="1111111QLbz7JHiBTspS962RLKV8GndWFwiEaqKM", name="Test Token"
        )
        transaction = Transaction(token=token)
        self.bot.account = test_account

        mock_client = AsyncMock(spec=AsyncClient)
        with patch("solana.rpc.async_api.AsyncClient", return_value=mock_client):
            result = await self.bot.send_buy_transaction(transaction)

            assert result is True
            assert token.mint in self.bot.tracked_tokens

    @pytest.mark.asyncio
    async def test_send_buy_transaction_failure(self, test_account):
        """Test sending a buy transaction when it fails."""
        token = Token(
            mint="1111111QLbz7JHiBTspS962RLKV8GndWFwiEaqKM", name="Test Token"
        )
        transaction = Transaction(token=token)
        self.bot.account = test_account

        mock_client = AsyncMock(spec=AsyncClient)
        self.bot._Bot__send_transaction = AsyncMock(
            side_effect=Exception("Transaction failed")
        )
        with patch("solana.rpc.async_api.AsyncClient", return_value=mock_client):
            result = await self.bot.send_buy_transaction(transaction)

            assert result is False

    @pytest.mark.asyncio
    async def test_run_create_transaction(self, load_file):
        """Test bot processing a 'create' transaction."""
        message = load_file("tests/etc/transactions/create.json")
        tx = Parser(json.loads(message)).parse()

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
        ), patch.object(
            self.bot, "send_buy_transaction", new_callable=AsyncMock, return_value=True
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            self.bot.subscribe_token_transactions.assert_called_once_with(
                mock_ws, tx.token.mint
            )
            self.bot.unsubscribe_new_tokens.assert_called_once_with(mock_ws)
            self.bot.send_buy_transaction.assert_called_once_with(tx)

    @pytest.mark.asyncio
    async def test_run_buy_transaction(self, load_file):
        """Test bot processing a 'buy' transaction."""
        message = load_file("tests/etc/transactions/buy.json")
        tx = Parser(json.loads(message)).parse()

        mock_ws = AsyncMock()
        mock_ws.__aiter__.return_value = [
            message
        ]  # Simulate WebSocket message streaming

        mock_connect = AsyncMock()
        mock_connect.__aenter__.return_value = mock_ws

        self.bot.tracked_tokens[tx.token.mint] = tx.token

        with patch("websockets.connect", return_value=mock_connect), patch.object(
            self.bot, "subscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_new_tokens", new_callable=AsyncMock
        ), patch.object(
            self.bot, "unsubscribe_token_transactions", new_callable=AsyncMock
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            assert self.bot.tracked_tokens[tx.token.mint].price == tx.token_price()

    @pytest.mark.asyncio
    async def test_run_sell_transaction(self, load_file):
        """Test bot processing a 'sell' transaction."""
        message = load_file("tests/etc/transactions/sell.json")
        tx = Parser(json.loads(message)).parse()

        self.bot.tracked_tokens[tx.token.mint] = deepcopy(tx.token)
        self.bot.tracked_tokens[tx.token.mint].price = 0.008

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
        ), patch.object(
            self.bot, "send_sell_transaction", new_callable=AsyncMock, return_value=True
        ):

            await self.bot.run()

            self.bot.subscribe_new_tokens.assert_called_once_with(mock_ws)
            self.bot.unsubscribe_token_transactions.calls = [
                call(mock_ws, tx.token),
                call(mock_ws, tx.token),
            ]
            self.bot.unsubscribe_new_tokens.asseunsubscribe_token_transactiort_called_once_with(
                mock_ws
            )
            self.bot.send_sell_transaction.assert_called_once_with(tx)
