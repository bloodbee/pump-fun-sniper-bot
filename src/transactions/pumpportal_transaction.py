import requests
import os


class PumpPortalTransaction:

    PUMPPORTAL_API_KEY = os.getenv("PUMPPORTAL_API_KEY", None)

    def __init__(self, transaction):
        self.transaction = transaction
        self.token = transaction.token if transaction.token else None
        self.token_address = str(self.token.mint) if self.token else None

    def send_buy_transaction(self, amount=0, slippage=3):
        if self.__assert_pumpportal_api_key() is True and self.__assert_tokens() is True:
            print(
                f"INFO [BUY HTTP] Buying token: {self.token.name} ({self.token_address})..."
            )
            try:

                response = requests.post(
                    url=f"https://pumpportal.fun/api/trade?api-key={self.PUMPPORTAL_API_KEY}",
                    data={
                        "action": "buy",
                        "mint": self.token_address,
                        "amount": amount,
                        "denominatedInSol": "true",
                        "slippage": slippage,
                        "priorityFee": 0.0001,
                        "pool": "pump",
                    },
                )
                data = response.json()
                if "errors" in data and data["errors"]:
                    print(f"ERROR [BUY HTTP] Buy transaction failed: {data['errors']}")
                    return False

                print(f"INFO [BUY HTTP] Buy transaction sent: {data['signature']}")
                return True

            except Exception as e:
                print(f"ERROR [BUY HTTP] Buy transaction failed: {e}")
                return False

        return False

    def send_sell_transaction(self, amount=100, slippage=3):
        """Send a SELL transaction using HTTP and pumportal API."""
        if self.__assert_pumpportal_api_key() is True and self.__assert_tokens() is True:

            print(f"INFO [SELL HTTP] Selling token: {self.token_address}")

            try:
                response = requests.post(
                    url=f"https://pumpportal.fun/api/trade?api-key={self.PUMPPORTAL_API_KEY}",
                    data={
                        "action": "sell",
                        "mint": self.token_address,
                        "amount": f"{amount}%",
                        "denominatedInSol": "false",
                        "slippage": slippage,
                        "priorityFee": 0.0001,
                        "pool": "pump",
                    },
                )
                data = response.json()
                if "errors" in data and data["errors"]:
                    print(
                        f"ERROR [SELL HTTP] Sell transaction failed: {data['errors']}"
                    )
                    return False

                print(f"INFO [SELL HTTP] Sell transaction sent: {data['signature']}")
                return True
            except Exception as e:
                print(f"ERROR [SELL HTTP] Sell transaction failed: {e}")
                return False
        return False

    def __assert_pumpportal_api_key(self):
        if self.PUMPPORTAL_API_KEY is None:
            print("ERROR [SELL HTTP] Missing PUMPPORTAL_API_KEY")
            return False
        return True

    def __assert_tokens(self):
        if not self.token and not self.token_address:
            print("ERROR [PUMPPORTAL TRANSACTION] No token or token address, aborting")
            return False
        return True
