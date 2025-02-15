import struct
import json
import os
import websockets
from dotenv import load_dotenv
from datetime import datetime, timedelta

from solana.rpc.types import TokenAccountOpts, TxOpts
from solders.instruction import Instruction, AccountMeta
from solana.rpc.api import Client
from solders.transaction import Transaction as SolTransaction
from solders.keypair import Keypair
from solders.message import Message
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.system_program import TransferParams, transfer
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.rpc.commitment import Confirmed
from spl.token.instructions import (
    get_associated_token_address,
    close_account,
    create_associated_token_account,
    CloseAccountParams,
)

from .storage import Storage
from .utils import Utils
from .constants import (
    GLOBAL,
    FEE_RECIPIENT,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    ASSOC_TOKEN_ACC_PROG,
    RENT,
    EVENT_AUTHORITY,
    PUMP_FUN_PROGRAM,
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
BUY_AMOUNT_SOL = float(os.getenv("BUY_AMOUNT_SOL"))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT")) / 100
TRAILING_STOP_LOSS = float(os.getenv("TRAILING_STOP_LOSS")) / 100
AUTO_SELL_AFTER_MINS = int(os.getenv("AUTO_SELL_AFTER_MINS", 0))  # 0 = disabled
MAX_TOKEN_TRACKED = int(os.getenv("MAX_TOKENS_TRACKED", 3))
PUMP_WS_URL = "wss://pumpportal.fun/api/data"


class Bot:
    def __init__(self, storage: Storage = None):
        self.storage: Storage = storage or Storage()
        self.tracked_tokens: dict[str, Token] = {}
        self.token_purchase_time: dict[str, dict] = {}
        self.account: Keypair = Keypair.from_base58_string(WALLET_PRIVATE_KEY)
        self.client = Client(SOLANA_RPC_URL)

    async def run(self) -> None:
        async with websockets.connect(PUMP_WS_URL) as ws:

            await self.subscribe_new_tokens(ws)

            async for message in ws:
                print(message)
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

    def send_buy_transaction(self, transaction):
        """Sends a buy transaction for the first available token."""
        token = transaction.token
        token_address = str(token.mint)
        if len(self.tracked_tokens) >= MAX_TOKEN_TRACKED:
            print(
                f"[SKIPPED] Max tracked tokens ({MAX_TOKEN_TRACKED}) reached. Cannot buy {token.name} ({token_address})"  # noqa: E501
            )
            return False  # Skip buying

        print(f"[BUY] Buying token: {token.name} ({token_address})...")

        associated_user = None
        token_account_instruction = None
        try:
            associated_user = (
                self.client.get_token_accounts_by_owner(
                    self.account.pubkey(), TokenAccountOpts(token.mint)
                )
                .value[0]
                .pubkey
            )
            token_account_instruction = None
        except Exception:
            associated_user = get_associated_token_address(
                self.account.pubkey(), token.mint
            )
            token_account_instruction = create_associated_token_account(
                self.account.pubkey(), self.account.pubkey(), token.mint
            )

        # Calculate amount of tokens
        amount = int(transaction.sol_for_tokens(BUY_AMOUNT_SOL) * TOKEN_DECIMALS)

        # Build instructions
        swap_instruction = self.__build_swap_instructions(
            transaction, associated_user, amount, 0
        )
        instructions = [
            set_compute_unit_limit(UNIT_BUDGET),
            set_compute_unit_price(UNIT_PRICE),
        ]
        if token_account_instruction:
            instructions.append(token_account_instruction)
        instructions.append(swap_instruction)
        try:
            # Send transaction
            tx_sig = self.__send_transaction(instructions)
            print(f"[INFO] Buy transaction sent: {tx_sig}, confirming transaction...")

            confirmed = Utils.confirm_txn(self.client, tx_sig)
            if confirmed is True:
                print(f"[SUCCESS] Buy transaction confirmed: {confirmed}")

                return confirmed
            else:
                print(f"[ERROR] Buy transaction failed: {token_address}")
                return False
        except Exception as e:
            print(f"[ERROR] Buy transaction failed: {e}")
            return False

    def send_sell_transaction(self, transaction):
        """Sells all available tokens at market price via Raydium."""
        token = transaction.token
        token_address = str(token.mint)
        print(f"[SELL] Selling token: {token.name} ({token_address})")

        sender = self.account.pubkey()

        # Get Associated Token Address (ATA)
        associated_user = get_associated_token_address(sender, token.mint)

        # Fetch Token Balance
        balance = self.__get_token_balance(associated_user)

        if balance == 0:
            print(f"[SKIPPED] No tokens to sell for {token_address}")
            return False

        print(f"[INFO] Selling {balance} tokens of {token_address}...")

        # Calculate amount of tokens
        amount = transaction.tokens_for_sol(balance)

        # Build instructions
        swap_instruction = self.__build_swap_instructions(
            transaction, associated_user, amount, 1
        )
        instructions = [
            set_compute_unit_limit(UNIT_BUDGET),
            set_compute_unit_price(UNIT_PRICE),
            swap_instruction,
            close_account(
                CloseAccountParams(
                    TOKEN_PROGRAM,
                    associated_user,
                    self.account.pubkey(),
                    self.account.pubkey(),
                )
            ),
        ]
        try:
            # Send transaction
            tx_sig = self.__send_transaction(instructions)
            print(f"[INFO] Sell transaction sent: {tx_sig}, confirming transaction...")

            confirmed = Utils.confirm_txn(self.client, tx_sig)
            print(f"[SUCCESS] Sell transaction confirmed: {confirmed}")

            return confirmed
        except Exception as e:
            print(f"[ERROR] Sell transaction failed: {e}")
            return False

    def __get_token_balance(self, ata_address):
        balance_response = self.client.get_token_account_balance(ata_address)
        return int(balance_response["result"]["value"]["amount"])

    def __send_transaction(self, instructions: list = []):
        # Compile message
        compiled_message = MessageV0.try_compile(
            self.account.pubkey(),
            instructions,
            [],
            self.client.get_latest_blockhash().value.blockhash,
        )
        # Send transaction
        res = self.client.send_transaction(
            txn=VersionedTransaction(compiled_message, [self.account]),
            opts=TxOpts(skip_preflight=True),
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
                    f"[AUTO-SELL] Selling token {token.name} ({token_address}) after {AUTO_SELL_AFTER_MINS} mins"  # noqa: E501
                )
                await self.__sell_token(ws, transaction)

    async def __websocket_disconnected(self, ws):
        # websocket connexion is closed
        await self.unsubscribe_new_tokens(ws)

        for token_address in list(self.tracked_tokens.keys()):
            await self.unsubscribe_token_transactions(ws, token_address)

    async def __buy_token(self, ws, tx):
        res = self.send_buy_transaction(tx)
        token_address = str(tx.token.mint)
        if res is True:
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
        res = self.send_sell_transaction(tx)
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

    def __build_instructions_keys(self, transaction, ata):
        return [
            AccountMeta(pubkey=GLOBAL, is_signer=False, is_writable=False),
            AccountMeta(pubkey=FEE_RECIPIENT, is_signer=False, is_writable=True),
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
            AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(pubkey=RENT, is_signer=False, is_writable=False),
            AccountMeta(pubkey=EVENT_AUTHORITY, is_signer=False, is_writable=False),
            AccountMeta(pubkey=PUMP_FUN_PROGRAM, is_signer=False, is_writable=False),
        ]

    def __build_swap_instructions(
        self,
        transaction,
        ata,
        amount=0,
        tx_type=0,
    ):
        data = bytearray()
        if tx_type == 0:
            data.extend(bytes.fromhex("66063d1201daebea"))
        else:
            data.extend(bytes.fromhex("33e685a4017f83ad"))
        data.extend(struct.pack("<Q", int(amount * TOKEN_DECIMALS)))
        data.extend(
            struct.pack("<Q", self.__calculate_preventiv_sol_amount(amount, tx_type))
        )
        return Instruction(
            PUMP_FUN_PROGRAM,
            bytes(data),
            self.__build_instructions_keys(transaction, ata),
        )
