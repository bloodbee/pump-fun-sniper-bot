# PUMP.FUN SNIPER BOT

The PUMP.FUN Sniper Bot is a tool designed to automate the process of sniping newly listed tokens on the [pump.fun](https://pump.fun) platform.

It aims to provide users with a competitive edge by executing trades faster than manual methods.

## Features

- **Automated Trading**: Automatically buys tokens as soon as they are listed.
- **RPC or HTTP**: Use RPC (the one you prefer) or HTTP ([https://pumpportal.fun/](https://pumpportal.fun/)) to trade.
- **Configurable Settings**: Customize the bot's behavior to suit your trading strategy.
- **Automatic sell**: Sell tokens automaticcaly using 3 strategies (see below).
- **Token storage**: Save tracked tokens with automatic reload.
- **Similiraty comparison**: Doesn't buy similar token names.

## Sell strategies

### Trailing stop-loss

The bot will sell tokens buy checking each "sell" transactions. If the current transaction price is lower than defined trailing stop-loss percentage, 100% of the tokens are sold.

### Automatic sell after X mins

The bot will automatically sell tokens after X mins passed, as defined per the user.
It can happen if a token keep going up (trailing stop-loss is not raised), or when there are no sell transactions.

### Take-profit

The bot will sell 50% of tokens at +25% price raise. Then will sell 25% of tokens remaining at +50% price raise.
Therefore, you will have gains and some tokens remaining.
It guarantees to have a profit when a token keep going to the moon.

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/yourusername/pump-fun-sniper-bot.git
    ```
2. Navigate to the project directory:
    ```bash
    cd pump-fun-sniper-bot
    ```
3. Activate a virtual environment and install dependencies:
    ```bash
    pip install
    ```

## Usage

1. Copy `sample.env` into `.env` file, update variables to suit your needs.
2. Start the bot:
    ```bash
    python main.py
    ```

## Limitations

Be aware that using a solana rpc is really slow and it takes multiples minutes to send and confirm a transaction.
You will always be in loose.

I recommend using PUMPPORTAL (https://pumpportal.fun/trading-api/setup), but be aware that the fees are higher (1% for pumpportal + pum.fun fees).

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE.txt) file for details.

## Disclaimer

Use this bot at your own risk. The developers are not responsible for any financial losses incurred while using this tool.