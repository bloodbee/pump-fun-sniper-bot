from dataclasses import dataclass
from typing import Optional
from solders.pubkey import Pubkey


@dataclass
class Token:
    """Model representation of a Token on pump.fun"""

    mint: Optional[Pubkey] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    price: Optional[float] = None

    def __deepcopy__(self, memo):
        """Deepcopy is used in test, and we need to fix pickle error."""
        return Token(
            mint=Pubkey.from_string(str(self.mint)),
            name=self.name,
            symbol=self.symbol,
            price=self.price
        )
