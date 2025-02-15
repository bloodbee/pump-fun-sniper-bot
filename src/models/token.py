from dataclasses import dataclass
from typing import Optional


@dataclass
class Token:
    """Model representation of a Token on pump.fun"""

    mint: Optional[str] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    price: Optional[float] = None
