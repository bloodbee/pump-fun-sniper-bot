from dataclasses import dataclass
from typing import Optional

from .token import Token


@dataclass
class Transaction:
    """Model representation of a transaction on pump.fun"""

    token: Optional[Token] = None
    traderPublicKey: Optional[str] = None
    txType: Optional[str] = None  # 'buy' or 'sell' or 'create'
    tokenAmount: Optional[float] = None
    solAmount: Optional[float] = None
    marketCapSol: Optional[float] = None
    initialBuy: Optional[float] = None
    bondingCurveKey: Optional[str] = None

    def token_price(self):
        if self.tokenAmount and self.solAmount and self.tokenAmount > 0:
            return self.solAmount / self.tokenAmount
        return None
