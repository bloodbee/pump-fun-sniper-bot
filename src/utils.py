import difflib
import os
import re
import struct
import hashlib
import time
import json
from solders.signature import Signature
from solana.rpc.types import TokenAccountOpts
from solana.rpc.commitment import Processed, Confirmed
from solders.pubkey import Pubkey
from dotenv import load_dotenv

from .constants import SOL_DECIMALS

load_dotenv()

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT")) / 100


class Utils:

    @staticmethod
    def is_similar_token(tokens: list, new_token_name: str) -> bool:
        """Checks if a token's name is too similar to a previously bought token."""
        for token in tokens:
            existing_name = token["name"]
            similarity = difflib.SequenceMatcher(
                None, existing_name.lower(), new_token_name.lower()
            ).ratio()

            if similarity >= SIMILARITY_THRESHOLD:
                print(
                    f"INFO [SKIPPED] {new_token_name} (Too similar to {existing_name}, Similarity: {similarity:.2f})"  # noqa: E501
                )
                return True
        return False

    @staticmethod
    async def get_token_balance(client, pub_key: Pubkey, mint: Pubkey) -> float | None:
        try:
            response = await client.get_token_accounts_by_owner_json_parsed(
                pub_key, TokenAccountOpts(mint=mint), commitment=Processed
            )

            accounts = response.value
            if accounts:
                token_amount = accounts[0].account.data.parsed["info"]["tokenAmount"][
                    "uiAmount"
                ]
                return float(token_amount)

            return None
        except Exception as e:
            print(f"Error fetching token balance: {e}")
            return None

    @staticmethod
    def calculate_discriminator(instruction_name):
        # Create a SHA256 hash object
        sha = hashlib.sha256()

        # Update the hash with the instruction name
        sha.update(instruction_name.encode("utf-8"))

        # Get the first 8 bytes of the hash
        discriminator_bytes = sha.digest()[:8]

        # Convert the bytes to a 64-bit unsigned integer (little-endian)
        discriminator = struct.unpack("<Q", discriminator_bytes)[0]

        return discriminator

    @staticmethod
    def calculate_preventiv_sol_amount(amount=0, tx_type=0):
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
