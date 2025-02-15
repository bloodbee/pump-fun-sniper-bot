import difflib
import os
import re
import time
import json
from solders.signature import Signature
from solana.rpc.commitment import Processed, Confirmed

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))


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
                    f"[SKIPPED] {new_token_name} (Too similar to {existing_name}, Similarity: {similarity:.2f})"  # noqa: E501
                )
                return True
        return False

    @staticmethod
    def confirm_txn(
        client, txn_sig: Signature, max_retries: int = 20, retry_interval: int = 3
    ) -> bool:
        retries = 1

        while retries < max_retries:
            try:
                txn_res = client.get_transaction(
                    txn_sig,
                    encoding="json",
                    commitment=Confirmed,
                    max_supported_transaction_version=0,
                )

                if txn_res is None:
                    print("[ERROR] Transaction not found.")
                    return False
                txn_json = json.loads(txn_res.value.transaction.meta.to_json())

                if txn_json["err"] is None:
                    return True

                if txn_json["err"]:
                    print("Transaction failed.")
                    return False
            except Exception:
                print("[WARNING] Awaiting confirmation... try count:", retries)
                retries += 1
                time.sleep(retry_interval)

        print("[ERROR] Max retries reached. Transaction confirmation failed.")
        return None
