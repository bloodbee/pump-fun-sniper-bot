from dataclasses import dataclass
from typing import Optional
from solders.pubkey import Pubkey  # type: ignore
from spl.token.instructions import get_associated_token_address

from .token import Token
from ..constants import PUMP_PROGRAM, SOL_DECIMALS, TOKEN_DECIMALS


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
    bondingCurveKey: Optional[Pubkey] = None
    associatedBondingCurveKey: Optional[Pubkey] = None
    vTokensInBondingCurve: Optional[float] = None
    vSolInBondingCurve: Optional[float] = None

    def token_price(self):
        if self.tokenAmount and self.solAmount and self.tokenAmount > 0:
            return self.solAmount / self.tokenAmount
        return None

    def set_associated_bonding_curve(self):
        bonding_curve, _ = Pubkey.find_program_address(
            ["bonding-curve".encode(), bytes(self.token.mint)], PUMP_PROGRAM
        )
        self.bondingCurveKey = bonding_curve
        self.associatedBondingCurveKey = get_associated_token_address(
            bonding_curve, self.token.mint
        )

    def sol_for_tokens(self, amount):
        """Calculate the amount of SOL received for a given amount of tokens."""
        sol_reserves = self.vSolInBondingCurve / SOL_DECIMALS
        token_reserves = self.vTokensInBondingCurve / TOKEN_DECIMALS
        new_sol_reserves = sol_reserves + amount
        new_token_reserves = (sol_reserves * token_reserves) / new_sol_reserves
        token_received = token_reserves - new_token_reserves
        return round(token_received)

    def tokens_for_sol(self, amount):
        """Calculate the amount of tokens received for a given amount of SOL."""
        sol_reserves = self.vSolInBondingCurve / SOL_DECIMALS
        token_reserves = self.vTokensInBondingCurve / TOKEN_DECIMALS
        new_token_reserves = token_reserves + amount
        new_sol_reserves = (sol_reserves * token_reserves) / new_token_reserves
        sol_received = sol_reserves - new_sol_reserves
        return sol_received
