import asyncio
import json
import os
import websockets
from dotenv import load_dotenv
from datetime import datetime, timedelta

from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .storage import Storage
from .utils import Utils
from .constants import (
    PUMP_GLOBAL,
    PUMP_FEE,
    PUMP_EVENT_AUTHORITY,
    PUMP_PROGRAM,
    SYSTEM_PROGRAM,
    SYSTEM_TOKEN_PROGRAM,
    SYSTEM_RENT,
    UNIT_BUDGET,
    UNIT_PRICE,
    SOL_DECIMALS,
    TOKEN_DECIMALS,
)
from .models.transaction import Transaction
from .models.token import Token
from .parser import Parser
from .transactions.pumpportal_transaction import PumpPortalTransaction
from .transactions.rpc_transaction import RpcTransaction

load_dotenv()

# Configuration
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
PUMPPORTAL_API_KEY = os.getenv("PUMPPORTAL_API_KEY", None)
BUY_AMOUNT_SOL = float(os.getenv("BUY_AMOUNT_SOL"))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT")) / 100
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_PERCENT"))
TRAILING_STOP_LOSS = float(os.getenv("TRAILING_STOP_LOSS")) / 100
AUTO_SELL_AFTER_MINS = int(os.getenv("AUTO_SELL_AFTER_MINS", 0))  # 0 = disabled
MAX_TOKEN_TRACKED = int(os.getenv("MAX_TOKENS_TRACKED", 3))
PUMP_WS_URL = "wss://pumpportal.fun/api/data"


class Bot:
    def __init__(self, storage: Storage = None, is_rpc: bool = True):
        self.storage: Storage = storage or Storage()
        self.tracked_tokens: dict[str, Token] = {}
        self.token_purchase_time: dict[str, dict] = {}
        self.partial_sales: dict[str, dict] = {}
        self.account: Keypair = Keypair.from_base58_string(WALLET_PRIVATE_KEY)
        self.is_rpc = is_rpc
        self.client = AsyncClient(SOLANA_RPC_URL)

    async def run(self) -> None:
        """Main method of the bot."""
        print("INFO [BOT] Starting bot with:")
        print("RPC_URL:", SOLANA_RPC_URL)
        print("WALLET:", self.account.pubkey())
        print("BUY_AMOUNT_SOL:", BUY_AMOUNT_SOL)
        print("SLIPPAGE_PERCENT:", SLIPPAGE_PERCENT)
        print("TRAILING_STOP_LOSS:", TRAILING_STOP_LOSS)
        print("AUTO_SELL_AFTER_MINS:", AUTO_SELL_AFTER_MINS)
        print("MAX_TOKEN_TRACKED:", MAX_TOKEN_TRACKED)
        print("PUMP_WS_URL:", PUMP_WS_URL)
        print("-----------------------------------------------")
        async with websockets.connect(PUMP_WS_URL) as ws:

            await self.subscribe_new_tokens(ws)

            await self.__reload_tracked_tokens(ws)

            async for message in ws:
                tx = Parser(json.loads(message)).parse()
                if tx:
                    token_address = str(tx.token.mint)

                    if tx.txType == "create" \
                       and Utils.is_similar_token(self.storage.tokens, tx.token.name) is False:
                        await self.__buy_token(ws, tx)

                    elif tx.txType == "buy":
                        price = tx.token_price()

                        if token_address in self.tracked_tokens:
                            self.tracked_tokens[token_address].price = price

                    elif tx.txType == "sell":
                        price = tx.token_price()
                        if token_address in self.tracked_tokens and price is not None:
                            await self.__sell_token(ws, tx)

                await self.__check_auto_sell(ws)

            await self.__websocket_disconnected(ws)

    async def subscribe_new_tokens(self, ws: websockets) -> None:
        print("INFO [WEBSOCKET] Subscribing to new token minted on pump.fun")
        await ws.send(json.dumps({"method": "subscribeNewToken"}))

    async def unsubscribe_new_tokens(self, ws: websockets) -> None:
        print("INFO [WEBSOCKET] Unsubscribing from new token minted on pump.fun")
        await ws.send(json.dumps({"method": "unsubscribeNewToken"}))

    async def subscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(f"INFO [WEBSOCKET] Subscribing to token {token_address} transactions")
        await ws.send(
            json.dumps({"method": "subscribeTokenTrade", "keys": [token_address]})
        )

    async def unsubscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(
            f"[INFO [WEBSOCKET] Unsubscribing from token {token_address} transactions"
        )
        await ws.send(
            json.dumps({"method": "unsubscribeTokenTrade", "keys": [token_address]})
        )

    async def __check_auto_sell(self, ws):
        """Auto-sell tokens after AUTO_SELL_AFTER_MINS minutes."""
        if AUTO_SELL_AFTER_MINS <= 0:
            return

        now = datetime.utcnow()
        due_tokens = []

        for token_address, tracked in list(self.token_purchase_time.items()):
            if now - tracked["buy_time"] >= timedelta(minutes=AUTO_SELL_AFTER_MINS):
                due_tokens.append((tracked["buy_time"], tracked["transaction"]))

        if not due_tokens:
            return

        due_tokens.sort()

        for _, transaction in due_tokens:
            token_address = str(transaction.token.mint)
            token = self.tracked_tokens.get(token_address)
            if token:
                print(
                    f"INFO [AUTO-SELL] Selling token {token.name} ({token_address}) after {AUTO_SELL_AFTER_MINS} mins"  # noqa: E501
                )
                await self.__sell_token(ws, transaction, True)

    async def __websocket_disconnected(self, ws):
        """Websocket has been disconnected."""
        # Unsubscribe from new tokens
        await self.unsubscribe_new_tokens(ws)

        # Ensure only active tokens are unsubscribed
        active_tokens = list(self.tracked_tokens.keys())
        if active_tokens:
            await asyncio.gather(
                *[
                    self.unsubscribe_token_transactions(ws, token_address)
                    for token_address in active_tokens
                ]
            )

        # Close websocket connection
        await self.client.close()

    async def __buy_token(self, ws, tx):
        """Buy a token using RPC or HTTP and save it to storage."""
        token = tx.token
        token_address = str(tx.token.mint)
        if len(self.tracked_tokens) >= MAX_TOKEN_TRACKED:
            print(
                f"WARNING [BUY HTTP] Max tracked tokens ({MAX_TOKEN_TRACKED}) reached. Cannot buy {token.name} ({token_address})"  # noqa: E501
            )
        else:
            res = False
            if self.is_rpc:
                rpc = RpcTransaction(self.client, tx, self.account)
                res = await rpc.send_buy_transaction(BUY_AMOUNT_SOL)
            else:
                res = PumpPortalTransaction(tx).send_buy_transaction(
                    amount=BUY_AMOUNT_SOL, slippage=SLIPPAGE_BPS
                )

            if res is True:
                await self.__save_token_bought(ws, tx, token_address)

    async def __sell_token(self, ws, tx, auto_sell=False):
        """Sell a token using RPC or HTTP and update storage."""
        token_address = str(tx.token.mint)
        token = self.tracked_tokens.get(token_address)

        if not token:
            print(f"WARNING [SELL HTTP] Token {token_address} not tracked. Skipping.")
            return

        if auto_sell is True:
            await self.__execute_sell(ws, tx, 100)
            return

        highest_price = self.tracked_tokens[token_address].price
        current_price = tx.token_price()

        res = False
        if current_price <= highest_price * (1 - TRAILING_STOP_LOSS):
            print(
                f"INFO [SELL HTTP] Selling 100% of {token.name} due to trailing stop-loss"
            )
            await self.__execute_sell(ws, tx, 100)  # Sell 100%
            return
        else:

            self.tracked_tokens[token_address].price = current_price

            if not self.is_rpc:
                if token_address not in self.partial_sales:
                    self.partial_sales[token_address] = {
                        "half_sold": False,
                        "quarter_sold": False,
                    }

                if (
                    current_price >= highest_price * 1.25
                    and not self.partial_sales[token_address]["half_sold"]  # noqa: W503
                ):
                    await self.__execute_sell(ws, tx, 50)  # Sell 50%
                    self.partial_sales[token_address][
                        "half_sold"
                    ] = True  # Mark first sell done

                elif (
                    current_price >= highest_price * 1.5625
                    and not self.partial_sales[token_address]["quarter_sold"]  # noqa: W503
                ):
                    await self.__execute_sell(ws, tx, 25)  # Sell 25%
                    self.partial_sales[token_address][
                        "quarter_sold"
                    ] = True  # Mark second sell done
            else:
                rpc = RpcTransaction(self.client, tx, self.account)
                res = await rpc.send_sell_transaction()

                if res is True:
                    await self.__clean_token_sold(ws, token_address)

    async def __clean_token_sold(self, ws, token_address):
        """Remove token sold from storage and tracked tokens. Unsubscribe from transactions."""
        await self.unsubscribe_token_transactions(ws, token_address)
        # Set token from storage to inactive
        for token in self.storage.tokens:
            if token["address"] == token_address:
                token["status"] = "inactive"
                break
        self.storage.save()
        # Remove token from tracked tokens
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
        # Remove token from purchase time
        if token_address in self.token_purchase_time:
            del self.token_purchase_time[token_address]

    async def __save_token_bought(self, ws, tx, token_address):
        buy_time = datetime.utcnow()
        # Update and save storage
        self.storage.tokens.append(
            {
                "name": tx.token.name,
                "address": token_address,
                "status": "active",
                "price": tx.token_price(),
                "buy_time": buy_time.isoformat(),
            }
        )
        self.storage.save()
        # Update tracked tokens, purchased datetime and partial sales
        tx.token.price = tx.token_price()
        self.tracked_tokens[token_address] = tx.token
        self.token_purchase_time[token_address] = {
            "transaction": tx,
            "buy_time": buy_time,
        }
        self.partial_sales[token_address] = {
            "half_sold": False,
            "quarter_sold": False,
        }
        await self.subscribe_token_transactions(ws, token_address)

    async def __execute_sell(self, ws, tx, percentage):
        """
        Executes a partial sell of a token.
        :param ws: WebSocket connection
        :param tx: Transaction data
        :param percentage: Percentage of total tokens to sell
        """
        token_address = str(tx.token.mint)

        # Only execute HTTP-based selling strategy
        if not self.is_rpc:
            print(f"INFO [SELL] Selling {percentage}% of {token_address}")

            res = PumpPortalTransaction(tx).send_sell_transaction(
                amount=percentage, slippage=SLIPPAGE_BPS
            )
            if res is True:
                print(
                    f"INFO [SELL HTTP] Successfully sold {percentage}% of {token_address}"
                )

                # If selling 100%, remove from tracked tokens
                if percentage == 100:
                    await self.__clean_token_sold(ws, token_address)
        else:
            rpc = RpcTransaction(self.client, tx, self.account)
            res = await rpc.send_sell_transaction()

            if res is True:
                await self.__clean_token_sold(ws, token_address)

    async def __reload_tracked_tokens(self, ws: websockets) -> None:
        """Reload tracked tokens from storage and subscribe to their transactions."""
        tasks = []
        for token in self.storage.tokens:
            token_address = token["address"]
            if token["status"] == "active":
                buy_time = (
                    datetime.fromisoformat(token["buy_time"])
                    if "buy_time" in token
                    else datetime.utcnow()
                )

                self.tracked_tokens[token_address] = Token(
                    name=token["name"], mint=token_address, price=token["price"]
                )
                self.token_purchase_time[token_address] = {
                    "transaction": Transaction(
                        token=self.tracked_tokens[token_address]
                    ),
                    "buy_time": buy_time,
                }
                tasks.append(self.subscribe_token_transactions(ws, token_address))

        await asyncio.gather(*tasks)
