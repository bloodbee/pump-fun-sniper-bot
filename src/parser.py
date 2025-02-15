from solders.pubkey import Pubkey
from .models.transaction import Transaction
from .models.token import Token


class Parser:
    """Parser for messages received via pump.fun API into a Transaction + Token."""

    def __init__(self, message):
        self.message = message

    def parse(self) -> Transaction:
        """Parse the JSON message into a Transaction object."""

        # Extract common fields
        txType = self.message.get("txType")

        mint = self.message.get("mint")
        if mint:
            token = Token(mint=Pubkey.from_string(mint))

            # If the transaction is a token creation (minting)
            if txType == "create":
                token.name = self.message.get("name")
                token.symbol = self.message.get("symbol")

            # Create the Transaction object
            tx = Transaction(
                token=token,
                traderPublicKey=self.message.get("traderPublicKey"),
                txType=txType,
                tokenAmount=self._safe_float("tokenAmount"),
                solAmount=self._safe_float("solAmount"),
                marketCapSol=self._safe_float("marketCapSol"),
                initialBuy=self._safe_float("initialBuy"),
            )

            if txType == "create":
                tx.vTokensInBondingCurve = self._safe_float("vTokensInBondingCurve")
                tx.vSolInBondingCurve = self._safe_float("vSolInBondingCurve")

            tx.set_associated_bonding_curve()

            tx.token.price = tx.token_price()

            return tx

    def _safe_float(self, key: str) -> float:
        """Helper method to safely convert a dictionary value to float, handling missing keys."""
        value = self.message.get(key)
        return float(value) if value is not None else None
