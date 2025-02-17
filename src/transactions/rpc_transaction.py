import asyncio
import struct
from solders.message import Message
from solana.rpc.types import TxOpts
from solders.instruction import Instruction, AccountMeta
from solana.rpc.commitment import Confirmed
from solders.transaction import Transaction as SolTransaction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from spl.token.instructions import (
    get_associated_token_address,
    close_account,
    create_associated_token_account,
    CloseAccountParams,
)
from ..constants import (
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
from ..utils import Utils


class RpcTransaction:

    def __init__(self, client, transaction, account):
        self.client = client
        self.transaction = transaction
        self.account = account
        self.token = transaction.token if transaction.token else None
        self.token_address = str(self.token.mint) if self.token else None

    async def send_buy_transaction(self, amount=0, max_retries=5):
        """Sends a buy transaction for the first available token using RPC."""

        if await self.client.is_connected() is True:
            print(f"INFO [BUY RPC] Buying token: {self.token.name} ({self.token_address})...")

            associated_token_account = get_associated_token_address(
                self.account.pubkey(), self.token.mint
            )

            await self.__create_ata(associated_token_account, self.token)

            # Calculate amount of tokens
            buy_amount = int(self.transaction.sol_for_tokens(amount) * TOKEN_DECIMALS)

            # Build instructions
            buy_instruction = self.__build_instructions(
                associated_token_account, buy_amount, 0
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

    async def send_sell_transaction(self):
        """Sells all available tokens at market price using RPC."""
        if await self.client.is_connected() is True:
            print(f"INFO [SELL RPC] Selling token: {self.token.name} ({self.token_address})")

            sender = self.account.pubkey()

            # Get Associated Token Address (ATA)
            associated_token_account = get_associated_token_address(sender, self.token.mint)

            # Fetch Token Balance
            token_balance = Utils.get_token_balance(sender, self.token.mint)

            if token_balance == 0 or token_balance is None:
                print(f"WARNING [SELL RPC] No tokens to sell for {self.token_address}")
                return False

            print(
                f"INFO [SELL RPC] Selling {token_balance} tokens of {self.token_address}..."
            )

            # Calculate amount of tokens
            sell_amount = self.transaction.tokens_for_sol(token_balance)

            # Build instructions
            sell_instruction = self.__build_instructions(
                self.transaction, associated_token_account, sell_amount, 1
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
                    asyncio.sleep(wait_time)
                else:
                    print(
                        "ERROR [ATA RPC] Max retries reached. Unable to create associated token account."  # noqa: E501
                    )
                    return False

    def __build_instructions(
        self,
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
            struct.pack("<Q", Utils.calculate_preventiv_sol_amount(amount, tx_type))
        )

        return Instruction(
            PUMP_PROGRAM,
            bytes(data),
            self.__get_instructions_accounts(ata),
        )

    def __get_instructions_accounts(self, ata):
        """Generate the accounts for a transaction."""
        return [
            AccountMeta(pubkey=PUMP_GLOBAL, is_signer=False, is_writable=False),
            AccountMeta(pubkey=PUMP_FEE, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=self.token.mint,
                is_signer=False,
                is_writable=False,
            ),
            AccountMeta(
                pubkey=self.transaction.bondingCurveKey,
                is_signer=False,
                is_writable=True,
            ),
            AccountMeta(
                pubkey=self.transaction.associatedBondingCurveKey,
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
