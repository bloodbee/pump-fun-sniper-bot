import struct
import asyncio
import json
import os
import requests
from time import sleep
import websockets
from dotenv import load_dotenv
from datetime import datetime, timedelta

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction, AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction as SolTransaction
from spl.token.instructions import (
    get_associated_token_address,
    close_account,
    create_associated_token_account,
    CloseAccountParams,
)

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

    async def send_rpc_buy_transaction(self, transaction, max_retries=5):
        """Sends a buy transaction for the first available token using RPC."""
        token = transaction.token
        token_address = str(token.mint)
        if len(self.tracked_tokens) >= MAX_TOKEN_TRACKED:
            print(
                f"WARNING [BUY RPC] Max tracked tokens ({MAX_TOKEN_TRACKED}) reached. Cannot buy {token.name} ({token_address})"  # noqa: E501
            )
            return False  # Skip buying

        if await self.client.is_connected() is True:
            print(f"INFO [BUY RPC] Buying token: {token.name} ({token_address})...")

            associated_token_account = get_associated_token_address(
                self.account.pubkey(), token.mint
            )

            await self.__create_ata(associated_token_account, token)

            # Calculate amount of tokens
            amount = int(transaction.sol_for_tokens(BUY_AMOUNT_SOL) * TOKEN_DECIMALS)

            # Build instructions
            buy_instruction = self.__build_instructions(
                transaction, associated_token_account, amount, 0
            )
            instructions = [
                set_compute_unit_limit(UNIT_BUDGET),
                set_compute_unit_price(UNIT_PRICE),
            ]

            instructions.append(buy_instruction)

            try:
                # Send transaction
                tx = await self.__send_transaction(instructions)
                print(
                    f"INFO [BUY RPC] Buy transaction sent: {tx} ; confirming transaction..."
                )

                confirmed = await self.client.confirm_transaction(
                    tx, commitment="confirmed"
                )
                return confirmed
            except Exception as e:
                print(f"ERROR [BUY RPC] Buy transaction failed: {e}")
                return False

    async def send_rpc_sell_transaction(self, transaction):
        """Sells all available tokens at market price using RPC."""
        token = transaction.token
        token_address = str(token.mint)
        if await self.client.is_connected() is True:
            print(f"INFO [SELL RPC] Selling token: {token.name} ({token_address})")

            sender = self.account.pubkey()

            # Get Associated Token Address (ATA)
            associated_token_account = get_associated_token_address(sender, token.mint)

            # Fetch Token Balance
            token_balance = Utils.get_token_balance(sender, token.mint)

            if token_balance == 0 or token_balance is None:
                print(f"WARNING [SELL RPC] No tokens to sell for {token_address}")
                return False

            print(
                f"INFO [SELL RPC] Selling {token_balance} tokens of {token_address}..."
            )

            # Calculate amount of tokens
            amount = transaction.tokens_for_sol(token_balance)

            # Build instructions
            sell_instruction = self.__build_instructions(
                transaction, associated_token_account, amount, 1
            )
            instructions = [
                set_compute_unit_limit(UNIT_BUDGET),
                set_compute_unit_price(UNIT_PRICE),
                sell_instruction,
                close_account(
                    CloseAccountParams(
                        SYSTEM_TOKEN_PROGRAM,
                        associated_token_account,
                        sender,
                        sender,
                    )
                ),
            ]
            try:
                # Send transaction
                tx = await self.__send_transaction(instructions)
                print(
                    f"INFO [SELL RPC] Sell transaction sent: {tx} ; confirming transaction..."
                )

                confirmed = await self.client.confirm_transaction(
                    tx, commitment="confirmed"
                )
                print(f"INFO [SELL RPC] Sell transaction confirmed: {confirmed}")

                return confirmed
            except Exception as e:
                print(f"ERROR [SELL RPC] Sell transaction failed: {e}")
                return False

    def send_http_buy_transaction(self, transaction):
        """Sends a BUY transaction using HTTP and pumportal API."""
        token = transaction.token
        token_address = str(token.mint)
        if len(self.tracked_tokens) >= MAX_TOKEN_TRACKED:
            print(
                f"WARNING [BUY HTTP] Max tracked tokens ({MAX_TOKEN_TRACKED}) reached. Cannot buy {token.name} ({token_address})"  # noqa: E501
            )
            return False  # Skip buying

        if PUMPPORTAL_API_KEY is None:
            print("ERROR [BUY HTTP] Missing PUMPPORTAL_API_KEY")
            return False

        try:
            print(f"INFO [BUY HTTP] Buying token: {token.name} ({token_address})...")

            response = requests.post(
                url=f"https://pumpportal.fun/api/trade?api-key={PUMPPORTAL_API_KEY}",
                data={
                    "action": "buy",
                    "mint": token_address,
                    "amount": BUY_AMOUNT_SOL,
                    "denominatedInSol": "true",
                    "slippage": SLIPPAGE_BPS,
                    "priorityFee": 0.001,
                    "pool": "pump",
                },
            )
            data = response.json()
            if "errors" in data and data["errors"]:
                print(f"ERROR [BUY HTTP] Buy transaction failed: {data['errors']}")
                return False

            print(f"INFO [BUY HTTP] Buy transaction sent: {data['signature']}")
            return True

        except Exception as e:
            print(f"ERROR [BUY HTTP] Buy transaction failed: {e}")
            return False

    def send_http_sell_transaction(self, transaction, percentage=100):
        """Send a SELL transaction using HTTP and pumportal API."""
        if PUMPPORTAL_API_KEY is None:
            print("ERROR [SELL HTTP] Missing PUMPPORTAL_API_KEY")
            return False

        token = transaction.token
        token_address = str(token.mint)

        print(f"INFO [SELL HTTP] Selling token: {token_address}")

        try:
            response = requests.post(
                url=f"https://pumpportal.fun/api/trade?api-key={PUMPPORTAL_API_KEY}",
                data={
                    "action": "sell",
                    "mint": token_address,
                    "amount": f"{percentage}%",
                    "denominatedInSol": "false",
                    "slippage": SLIPPAGE_BPS,
                    "priorityFee": 0.001,
                    "pool": "pump",
                },
            )
            data = response.json()
            if "errors" in data and data["errors"]:
                print(f"ERROR [SELL HTTP] Sell transaction failed: {data['errors']}")
                return False

            print(f"INFO [SELL HTTP] Sell transaction sent: {data['signature']}")
            return True
        except Exception as e:
            print(f"ERROR [SELL HTTP] Sell transaction failed: {e}")
            return False

    async def __send_transaction(self, instructions: list = []):
        """Send a transaction using RPC."""
        # Compile message
        latest_blockhash = await self.client.get_latest_blockhash()
        msg = Message(instructions, self.account.pubkey())
        tx = SolTransaction([self.account], msg, latest_blockhash.value.blockhash)
        # Send transaction
        res = await self.client.send_transaction(
            txn=tx,
            opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
        )

        return res.value

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
                await self.__sell_token(ws, transaction)

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
        res = (
            await self.send_rpc_buy_transaction(tx)
            if self.is_rpc
            else self.send_http_buy_transaction(tx)
        )
        token_address = str(tx.token.mint)
        if res is True:
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

    async def __sell_token(self, ws, tx):
        """Sell a token using RPC or HTTP and update storage."""
        token_address = str(tx.token.mint)
        token = self.tracked_tokens.get(token_address)

        if not token:
            print(f"WARNING [SELL HTTP] Token {token_address} not tracked. Skipping.")
            return

        highest_price = self.tracked_tokens[token_address].price
        current_price = tx.token_price()

        res = False
        if current_price <= highest_price * (1 - TRAILING_STOP_LOSS):
            print(f"INFO [SELL HTTP] Selling 100% of {token.name} due to trailing stop-loss")
            await self.__execute_sell(ws, tx, 100)  # Sell 100%
            return
        else:

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
                res = await self.send_rpc_sell_transaction(tx)

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

            res = self.send_http_sell_transaction(tx, percentage)
            if res is True:
                print(f"INFO [SELL HTTP] Successfully sold {percentage}% of {token_address}")

                # If selling 100%, remove from tracked tokens
                if percentage == 100:
                    await self.__clean_token_sold(ws, token_address)

    def __calculate_preventiv_sol_amount(self, amount=0, tx_type=0):
        """
        Depending if its a buy or sell transaction,
        calculate the min or max amout of sol to spend
        """
        slippage_adjustment = 1
        if tx_type == 0:
            slippage_adjustment = 1 + (SLIPPAGE_PERCENT / 100)
        else:
            slippage_adjustment = 1 - (SLIPPAGE_PERCENT / 100)

        return int((amount * slippage_adjustment) * SOL_DECIMALS)

    def __get_instructions_accounts(self, transaction, ata):
        """Generate the accounts for a transaction."""
        return [
            AccountMeta(pubkey=PUMP_GLOBAL, is_signer=False, is_writable=False),
            AccountMeta(pubkey=PUMP_FEE, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=transaction.token.mint,
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=transaction.bondingCurveKey,
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(
                pubkey=transaction.associatedBondingCurveKey,
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(pubkey=ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.account.pubkey(), is_signer=True, is_writable=True),
            AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(
                pubkey=SYSTEM_TOKEN_PROGRAM, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=SYSTEM_RENT, is_signer=False, is_writable=False),
            AccountMeta(
                pubkey=PUMP_EVENT_AUTHORITY, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=PUMP_PROGRAM, is_signer=False, is_writable=False),
        ]

    def __build_instructions(
        self,
        transaction,
        ata,
        amount=0,
        tx_type=0,
    ):
        """Build instructions used inside a transaction."""
        data = bytearray()
        if tx_type == 0:
            data.extend(struct.pack("<Q", 16927863322537952870))
        else:
            data.extend(struct.pack("<Q", 12502976635542562355))
        data.extend(struct.pack("<Q", int(amount * TOKEN_DECIMALS)))
        data.extend(
            struct.pack("<Q", self.__calculate_preventiv_sol_amount(amount, tx_type))
        )

        return Instruction(
            PUMP_PROGRAM,
            bytes(data),
            self.__get_instructions_accounts(transaction, ata),
        )

    async def __create_ata(self, ata, token, max_retries=5):
        """Create an associated token account with retries strategy."""
        for ata_attempt in range(max_retries):
            try:
                account_info = await self.client.get_account_info(ata)
                if account_info.value is None:
                    print(
                        f"INFO [ATA RPC] Creating associated token account (Attempt {ata_attempt + 1})..."  # noqa: E501
                    )
                    create_ata_ix = create_associated_token_account(
                        self.account.pubkey(), self.account.pubkey(), token.mint
                    )
                    message = Message([create_ata_ix], self.account.pubkey())
                    latest_blockhash = await self.client.get_latest_blockhash()
                    create_ata_tx = SolTransaction(
                        [self.account],
                        message,
                        latest_blockhash.value.blockhash,
                    )
                    await self.client.send_transaction(
                        txn=create_ata_tx,
                        opts=TxOpts(
                            skip_preflight=True, preflight_commitment=Confirmed
                        ),
                    )
                    print(f"INFO [ATA RPC] Associated token account address: {ata}")
                    break
                else:
                    print("WARNING [ATA RPC] Associated token account already exists.")
                    print(f"INFO [ATA RPC] Associated token account address: {ata}")
                    break
            except Exception:
                print(
                    f"WARNING [ATA RPC] Attempt {ata_attempt + 1} to create associated token account failed"  # noqa: E501
                )
                if ata_attempt < max_retries - 1:
                    wait_time = 2**ata_attempt
                    sleep(wait_time)
                else:
                    print(
                        "ERROR [ATA RPC] Max retries reached. Unable to create associated token account."  # noqa: E501
                    )
                    return False

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
