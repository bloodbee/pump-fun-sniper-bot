from .models.transaction import Transaction
from .models.token import Token


class Parser:
    """Parser for messages received via pump.fun API into a Transaction + Token."""

    def __init__(self, message):
        self.message = message

    def parse(self):
        """Parse the JSON message into a Transaction object."""

        # Extract common fields
        txType = self.message.get("txType")
        token = Token(mint=self.message.get("mint"))

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
            bondingCurveKey=self.message.get("bondingCurveKey")
        )

        tx.token.price = tx.token_price()

        return tx

    def _safe_float(self, key):
        """Helper method to safely convert a dictionary value to float, handling missing keys."""
        value = self.message.get(key)
        return float(value) if value is not None else None
