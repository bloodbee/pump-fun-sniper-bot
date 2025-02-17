# PUMP.FUN SNIPER BOT

The PUMP.FUN Sniper Bot is a tool designed to automate the process of sniping newly listed tokens on the [pump.fun](https://pump.fun) platform.

It aims to provide users with a competitive edge by executing trades faster than manual methods.

## Features

- **Automated Trading**: Automatically buy tokens as soon as they are listed.
- **RPC or HTTP**: Use RPC (the one you prefer) or HTTP ([https://pumpportal.fun/](https://pumpportal.fun/)) to trade.
- **Configurable Settings**: Customize the bot's behavior to suit your trading strategy.
- **Automatic sell**: Sell tokens automatically using 3 strategies (see below).
- **Token storage**: Save tracked tokens with automatic reload.
- **Similiraty comparison**: Doesn't buy similar token names.

## Sell strategies

### Trailing stop-loss

The bot sells tokens by checking each sale transaction. If the current transaction price is below the defined stop-loss percentage, 100% of the tokens are sold.

### Automatic sell after X mins

The bot will automatically sell tokens after X minutes, as defined by the user.
This can happen if a token continues to rise (the trailing stop-loss is not lifted), or when there are no sell transactions.

### Take-profit

The bot will sell 50% of the tokens at a price increase of +25%. It will then sell 25% of the remaining tokens at a price increase of +50%.

As a result, you'll have a profit and a few tokens left over.
This is your guarantee of a profit when a token continues to rise to the moon.

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

Be aware that using a solana rpc is very slow and that it takes several minutes to send and confirm a transaction.
You'll always be on hold.

I recommend using PUMPPORTAL (https://pumpportal.fun/trading-api/setup), but the fees are higher (1% for pumpportal + pump.fun fees).

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE.txt) file for details.

## Disclaimer

Use this bot at your own risk. The developers are not responsible for any financial losses incurred while using this tool.