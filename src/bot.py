import struct
import json
import os
import requests
from time import sleep
import websockets
from dotenv import load_dotenv
from datetime import datetime, timedelta

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TokenAccountOpts, TxOpts
from solders.commitment_config import CommitmentLevel
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction, AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.rpc.config import RpcSendTransactionConfig
from solders.rpc.requests import SendVersionedTransaction
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction as SolTransaction
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
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
        self.account: Keypair = Keypair.from_base58_string(WALLET_PRIVATE_KEY)
        self.is_rpc = is_rpc

    async def run(self) -> None:
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

            async for message in ws:
                tx = Parser(json.loads(message)).parse()
                if tx:
                    token_address = str(tx.token.mint)

                    if tx.txType == "create":
                        await self.__buy_token(ws, tx)

                    elif tx.txType == "buy":
                        price = tx.token_price()

                        if token_address in self.tracked_tokens:
                            self.tracked_tokens[token_address].price = price

                    elif tx.txType == "sell":
                        price = tx.token_price()
                        if token_address in self.tracked_tokens and price is not None:
                            highest_price = self.tracked_tokens[token_address].price
                            if price <= highest_price * (1 - TRAILING_STOP_LOSS):
                                await self.__sell_token(ws, tx)

                await self.__check_auto_sell(ws)

            await self.__websocket_disconnected(ws)

    async def subscribe_new_tokens(self, ws: websockets) -> None:
        print("INFO [WEBSOCKET] Subscribing to new token minted on pump.fun")
        payload = {
            "method": "subscribeNewToken",
        }
        await ws.send(json.dumps(payload))

    async def unsubscribe_new_tokens(self, ws: websockets) -> None:
        print("INFO [WEBSOCKET] Unsubscribing from new token minted on pump.fun")
        payload = {
            "method": "unsubscribeNewToken",
        }
        await ws.send(json.dumps(payload))

    async def subscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(f"INFO [WEBSOCKET] Subscribing to token {token_address} transactions")
        payload = {"method": "subscribeTokenTrade", "keys": [token_address]}
        await ws.send(json.dumps(payload))

    async def unsubscribe_token_transactions(
        self, ws: websockets, token_address: str
    ) -> None:
        print(
            f"[INFO [WEBSOCKET] Unsubscribing from token {token_address} transactions"
        )
        payload = {"method": "unsubscribeTokenTrade", "keys": [token_address]}
        await ws.send(json.dumps(payload))

    async def send_rpc_buy_transaction(self, transaction, max_retries=5):
        """Sends a buy transaction for the first available token using RPC."""
        token = transaction.token
        token_address = str(token.mint)
        if len(self.tracked_tokens) >= MAX_TOKEN_TRACKED:
            print(
                f"WARNING [BUY RPC] Max tracked tokens ({MAX_TOKEN_TRACKED}) reached. Cannot buy {token.name} ({token_address})"  # noqa: E501
            )
            return False  # Skip buying

        async with AsyncClient(SOLANA_RPC_URL) as client:
            await client.is_connected()

            print(f"INFO [BUY RPC] Buying token: {token.name} ({token_address})...")

            associated_token_account = get_associated_token_address(
                self.account.pubkey(), token.mint
            )

            await self.__create_ata(client, associated_token_account, token)

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
                tx = await self.__send_transaction(client, instructions)
                print(
                    f"INFO [BUY RPC] Buy transaction sent: {tx} ; confirming transaction..."
                )

                confirmed = await client.confirm_transaction(tx, commitment="confirmed")
                return confirmed
            except Exception as e:
                print(f"ERROR [BUY RPC] Buy transaction failed: {e}")
                return False

    async def send_rpc_sell_transaction(self, transaction):
        """Sells all available tokens at market price using RPC."""
        async with AsyncClient(SOLANA_RPC_URL) as client:
            await client.is_connected()

            token = transaction.token
            token_address = str(token.mint)
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
                tx = await self.__send_transaction(client, instructions)
                print(
                    f"INFO [SELL RPC] Sell transaction sent: {tx} ; confirming transaction..."
                )

                confirmed = await client.confirm_transaction(tx, commitment="confirmed")
                print(f"INFO [SELL RPC] Sell transaction confirmed: {confirmed}")

                return confirmed
            except Exception as e:
                print(f"ERROR [SELL RPC] Sell transaction failed: {e}")
                return False

    def send_http_buy_transaction(self, transaction):
        """
        Sends a buy transaction for the first available token using HTTP.

        Note: It works only using quicknode endpoint with METIS add-on activated.
        """
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
                    "amount": int(BUY_AMOUNT_SOL * TOKEN_DECIMALS),
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

    async def send_http_sell_transaction(self, transaction):
        if PUMPPORTAL_API_KEY is None:
            print("ERROR [SELL HTTP] Missing PUMPPORTAL_API_KEY")
            return False

        async with AsyncClient(SOLANA_RPC_URL) as client:
            await client.is_connected()

            token = transaction.token
            token_address = str(token.mint)

            print(f"INFO [SELL HTTP] Selling token: {token_address}")

            # Fetch Token Balance
            token_balance = Utils.get_token_balance(
                client, self.account.pubkey(), token.mint
            )
            print("TOKEN BALANCE", token_balance)

            if token_balance == 0 or token_balance is None:
                print(f"WARNING [SELL HTTP] No tokens to sell for {token_address}")
                return False

            try:
                response = requests.post(
                    url=f"https://pumpportal.fun/api/trade?api-key={PUMPPORTAL_API_KEY}",
                    data={
                        "action": "sell",
                        "mint": token_address,
                        "amount": "100%",
                        "denominatedInSol": "false",
                        "slippage": SLIPPAGE_BPS,
                        "priorityFee": 0.001,
                        "pool": "pump",
                    },
                )
                data = response.json()
                if "errors" in data and data["errors"]:
                    print(
                        f"ERROR [SELL HTTP] Sell transaction failed: {data['errors']}"
                    )
                    return False

                print(f"INFO [SELL HTTP] Sell transaction sent: {data['signature']}")
                return True
            except Exception as e:
                print(f"ERROR [SELL HTTP] Sell transaction failed: {e}")
                return False

    async def __send_transaction(self, client, instructions: list = []):
        # Compile message
        latest_blockhash = await client.get_latest_blockhash()
        msg = Message(instructions, self.account.pubkey())
        tx = SolTransaction([self.account], msg, latest_blockhash.value.blockhash)
        # Send transaction
        res = await client.send_transaction(
            txn=tx,
            opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
        )

        return res.value

    async def __check_auto_sell(self, ws):
        if AUTO_SELL_AFTER_MINS <= 0:
            return  # Feature disabled

        now = datetime.utcnow()
        tokens_to_sell = [
            tracked["transaction"]
            for token, tracked in self.token_purchase_time.items()
            if now - tracked["buy_time"] >= timedelta(minutes=AUTO_SELL_AFTER_MINS)
        ]

        for transaction in tokens_to_sell:
            token_address = str(transaction.token.mint)
            token = self.tracked_tokens.get(token_address)
            if token:
                print(
                    f"INFO [AUTO-SELL] Selling token {token.name} ({token_address}) after {AUTO_SELL_AFTER_MINS} mins"  # noqa: E501
                )
                await self.__sell_token(ws, transaction)

    async def __websocket_disconnected(self, ws):
        # websocket connexion is closed
        await self.unsubscribe_new_tokens(ws)

        for token_address in list(self.tracked_tokens.keys()):
            await self.unsubscribe_token_transactions(ws, token_address)

    async def __buy_token(self, ws, tx):
        res = (
            await self.send_rpc_buy_transaction(tx)
            if self.is_rpc
            else self.send_http_buy_transaction(tx)
        )
        token_address = str(tx.token.mint)
        if res:
            # Update and save storage
            self.storage.tokens.append(
                {"name": tx.token.name, "address": token_address}
            )
            self.storage.save()
            # Update tracked tokens and purchased datetime
            self.tracked_tokens[token_address] = tx.token
            self.token_purchase_time[token_address] = {
                "transaction": tx,
                "buy_time": datetime.utcnow(),
            }
            await self.subscribe_token_transactions(ws, token_address)

    async def __sell_token(self, ws, tx):
        res = (
            await self.send_rpc_sell_transaction(tx)
            if self.is_rpc
            else await self.send_http_sell_transaction(tx)
        )
        token_address = str(tx.token.mint)
        if res:
            await self.unsubscribe_token_transactions(ws, token_address)
            # Remove token from storage, tracked_toekns and token_purchased_time
            self.storage.tokens = [
                t for t in self.storage.tokens if t["address"] != token_address
            ]
            self.storage.save()
            if token_address in self.tracked_tokens:
                del self.tracked_tokens[token_address]
            if token_address in self.token_purchase_time:
                del self.token_purchase_time[token_address]

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

    async def __create_ata(self, client, ata, token, max_retries=5):
        # create associated account with retries
        for ata_attempt in range(max_retries):
            try:
                account_info = await client.get_account_info(ata)
                if account_info.value is None:
                    print(
                        f"INFO [ATA RPC] Creating associated token account (Attempt {ata_attempt + 1})..."  # noqa: E501
                    )
                    create_ata_ix = create_associated_token_account(
                        self.account.pubkey(), self.account.pubkey(), token.mint
                    )
                    message = Message([create_ata_ix], self.account.pubkey())
                    latest_blockhash = await client.get_latest_blockhash()
                    create_ata_tx = SolTransaction(
                        [self.account],
                        message,
                        latest_blockhash.value.blockhash,
                    )
                    await client.send_transaction(
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
