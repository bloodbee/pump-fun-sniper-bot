import asyncio
import json
import os
import websockets
from dotenv import load_dotenv
from datetime import datetime, timedelta

from solana.rpc.async_api import AsyncClient
from solders.transaction import Transaction as SolTransaction
from solders.keypair import Keypair
from solders.message import Message
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.rpc.commitment import Confirmed
from spl.token.instructions import (
    get_associated_token_address,
    transfer_checked,
    close_account,
    TransferCheckedParams,
)

from .storage import Storage
from .utils import Utils

from .models.transaction import Transaction
from .models.token import Token
from .parser import Parser

load_dotenv()

# Configuration
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
BUY_AMOUNT_SOL = float(os.getenv("BUY_AMOUNT_SOL"))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT")) / 100
TRAILING_STOP_LOSS = float(os.getenv("TRAILING_STOP_LOSS")) / 100
AUTO_SELL_AFTER_MINS = int(
    os.getenv("AUTO_SELL_AFTER_MINS", 0)
)  # Default to 0 (disabled)
PUMP_WS_URL = "wss://pumpportal.fun/api/data"


class Bot:
    def __init__(self, storage: Storage = None):
        self.storage: Storage = storage or Storage()
        self.tracked_tokens: dict[str, Token] = {}
        self.token_purchase_time: dict[str, dict] = {}
        self.mutex: asyncio.Lock = asyncio.Lock()
        self.account: Keypair = Keypair.from_base58_string(WALLET_PRIVATE_KEY)

    async def run(self) -> None:
        async with websockets.connect(PUMP_WS_URL) as ws:

            await self.subscribe_new_tokens(ws)

            async for message in ws:
                tx = Parser(json.loads(message)).parse()
                token_address = tx.token.mint

                if tx.txType == "create":
                    await self.subscribe_token_transactions(ws, token_address)
                    await self.send_buy_transaction(tx)

                elif tx.txType == "buy":
                    price = tx.token_price()

                    if token_address in self.tracked_tokens:
                        self.tracked_tokens[token_address].price = price

                elif tx.txType == "sell":
                    price = tx.token_price()
                    if token_address in self.tracked_tokens and price is not None:
                        highest_price = self.tracked_tokens[token_address].price
                        if price <= highest_price * (1 - TRAILING_STOP_LOSS):
                            await self.__sell_token(ws, tx, True)

                await self.__check_auto_sell(ws)

            await self.__websocket_disconnected(ws)

    async def subscribe_new_tokens(self, ws: websockets) -> None:
        print("[INFO] Subscribing to new token minted on pump.fun")
        payload = {
            "method": "subscribeNewToken",
        }
        await ws.send(json.dumps(payload))

    async def unsubscribe_new_tokens(self, ws: websockets) -> None:
        print("[INFO] Unsubscribing from new token minted on pump.fun")
        payload = {
            "method": "unsubscribeNewToken",
        }
        await ws.send(json.dumps(payload))

    async def subscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(f"[INFO] Subscribing to token {token_address} transactions")
        payload = {"method": "subscribeTokenTrade", "keys": [token_address]}
        await ws.send(json.dumps(payload))

    async def unsubscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(f"[INFO] Unsubscribing from token {token_address} transactions")
        payload = {"method": "unsubscribeTokenTrade", "keys": [token_address]}
        await ws.send(json.dumps(payload))

    async def send_buy_transaction(self, transaction):
        """Sends a buy transaction for the first available token."""
        async with AsyncClient(SOLANA_RPC_URL) as client:
            await client.is_connected()
            async with self.mutex:
                token = transaction.token
                print(f"[INFO] Buying token: {token.name} ({token.mint})")
                receiver = (
                    Pubkey.from_string(token.mint)
                    if isinstance(token.mint, str)
                    else token.mint
                )

                # Construct transaction
                instructions = [
                    transfer(
                        TransferParams(
                            from_pubkey=self.account.pubkey(),
                            to_pubkey=receiver,
                            lamports=int(BUY_AMOUNT_SOL * 1e9),
                        )
                    )
                ]
                try:
                    # Send transaction
                    response = await self.__send_transaction(client, instructions)
                    print(f"[SUCCESS] Buy Transaction Sent: {response}")
                    # update and save storage
                    self.storage.tokens.append(
                        {"name": token.name, "address": str(receiver)}
                    )
                    self.storage.save()
                    # Update tracked tokens and purchased datetime
                    self.tracked_tokens[str(token.mint)] = token
                    self.token_purchase_time[str(token.mint)] = {
                        'transaction': transaction,
                        'buy_time': datetime.utcnow()
                    }
                    return True
                except Exception as e:
                    print(f"[ERROR] Buy transaction failed: {e}")
                    return False

    async def send_sell_transaction(self, transaction):
        """Sells all available tokens at market price via Raydium."""
        async with AsyncClient(SOLANA_RPC_URL) as client:
            await client.is_connected()
            async with self.mutex:
                token = transaction.token
                print(f"[SELL] Selling token: {token.name} ({token.mint})")

                sender = self.account.pubkey()

                # Get Associated Token Address (ATA)
                ata_address = get_associated_token_address(
                    sender, Pubkey.from_string(token.mint)
                )

                # Fetch Token Balance
                balance = await self.__get_token_balance(client, ata_address)

                if balance == 0:
                    print(f"[SKIPPED] No tokens to sell for {token.mint}")
                    return False

                print(f"[INFO] Selling {balance} tokens of {token.mint}")

                # Construct Sell Order via pum fun liquidity pool + close ATA to save rent
                instructions = [
                    transfer_checked(
                        TransferCheckedParams(
                            source=ata_address,
                            dest=Pubkey.from_string(transaction.bondingCurveKey),
                            owner=sender,
                            amount=balance,
                            decimals=10,
                            mint=Pubkey.from_string(token.mint),
                            program_id=TOKEN_PROGRAM_ID,
                        )
                    ),
                ]
                try:
                    # Send transaction
                    response = await self.__send_transaction(
                        client, instructions, sender
                    )
                    print(f"[SUCCESS] Sell transaction sent: {response}")

                    # Remove token from storage
                    self.storage.tokens = [
                        t for t in self.storage.tokens if t["address"] != token.mint
                    ]
                    self.storage.save()
                    if token.mint in self.tracked_tokens:
                        del self.tracked_tokens[token.mint]
                    return True
                except Exception as e:
                    print(f"[ERROR] Sell transaction failed: {e}")
                    return False

    async def __get_token_balance(self, client, ata_address):
        balance_response = await client.get_token_account_balance(ata_address)
        return int(balance_response["result"]["value"]["amount"])

    async def __send_transaction(self, client, instructions):
        latest_blockhash = await client.get_latest_blockhash()
        msg = Message(instructions, self.account.pubkey())
        txn = SolTransaction([self.account], msg, latest_blockhash.value.blockhash)
        return await client.send_transaction(txn)

    async def __check_auto_sell(self, ws):
        if AUTO_SELL_AFTER_MINS <= 0:
            return  # Feature disabled

        now = datetime.utcnow()
        tokens_to_sell = [
            tracked['transaction']
            for token, tracked in self.token_purchase_time.items()
            if now - tracked['buy_time'] >= timedelta(minutes=AUTO_SELL_AFTER_MINS)
        ]

        for transaction in tokens_to_sell:
            token_address = transaction.token.mint
            token = self.tracked_tokens.get(token_address)
            if token:
                print(
                    f"[AUTO-SELL] Selling token {token.name} ({token.mint}) after {AUTO_SELL_AFTER_MINS} mins"  # noqa: E501
                )
                await self.__sell_token(ws, transaction, True)

    async def __websocket_disconnected(self, ws):
        # websocket connexion is closed
        await self.unsubscribe_new_tokens(ws)

        for token_address in list(self.tracked_tokens.keys()):
            await self.unsubscribe_token_transactions(ws, token_address)

    async def __sell_token(self, ws, tx, auto_sell=False):
        res = await self.send_sell_transaction(tx)
        token_address = str(tx.token.mint)
        if res:
            await self.unsubscribe_token_transactions(ws, token_address)
            if auto_sell and token_address in self.token_purchase_time:
                del self.token_purchase_time[token_address]  # Remove from tracking
