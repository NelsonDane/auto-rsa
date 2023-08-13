# AutoRSA Discord Bot and CLI Tool
A CLI tool and Discord bot to buy and sell the same amount of stocks across multiple accounts!

## What is RSA?
RSA stands for "Reverse Split Arbitrage." This is a strategy where you buy the same amount of stocks in multiple accounts across multiple brokers right before a stock performs a reverse split. Once the stock splits and your fractional share is rounded up to a full share, you profit!

This project will allow you to maximize your profits by being able to easily manage multiple accounts across different brokerages, buying and selling as needed.

## Discord Bot Installation
To create your Discord bot and get your `DISCORD_TOKEN`, follow this [guide](guides/discordBot.md).
### Docker
1. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
2. Using the provided [docker-compose.yml](docker-compose.yml) file, run `docker compose up -d`
3. The bot should appear online (You can also do `!ping` to check). 

### Always Running Python Script
Make sure python3-pip is installed
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
4. Run `python autoRSA.py` (See below for more command explanations)

## CLI Tool Installation
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template.
4. Run the script using `python pythonRSA.py` plus the command you want to run (See below for more command explanations)

## Usage
If running as a Discord bot, append `!rsa` to the beginning of each command.
If running from the CLI Tool, append `python autoRSA.py` to the beginning of each command.

To buy and sell stocks, use this command:

`<action> <amount> <ticker> <accounts> <dry>`

For example, to buy 1 STAF in all accounts:

`buy 1 STAF all false`

For a dry run of the above command in Robinhood only:

`buy 1 STAF robinhood true`

For a real run on Ally and Robinhood, but not Schwab:

`buy 1 STAF ally,robinhood not schwab false`

For a real run on Ally and Robinhood but not Schwab buying both STAF and AREB:

`buy 1 STAF,AREB ally,robinhood not schwab false`

To check your account holdings:

`holdings <accounts>`

To restart the Discord bot:

`!restart` (without appending `!rsa`)

For help:

`!help` (without appending `!rsa`)

### Parameters
- `<action>`: string, "buy" or "sell"
- `<amount>`: integer, Amount to buy or sell.
- `<ticker>`: string, The stock ticker to buy or sell. Separate multiple tickers with commas and no spaces.
- `<accounts>`: string, What brokerage to run command in (robinhood, schwab, etc, or all). Separate multiple brokerages with commas and no spaces.
- `<not accounts>`: string proceeding `not`, What brokerages to exclude from command. Separate multiple brokerages with commas and no spaces.
- `<dry>`: boolean, Whether to run in `dry` mode (in which no transactions are made. Useful for testing). Set to `True`, `False`, or just write `dry` for`True`. Defaults to `True`, so if you want to run a real transaction, you must set this explicitly.

### Testing your Login Credentials
To test your login credentials, run `python testLogin.py`. This will print all your `.env` variables and attempt to log in to each brokerage. If you get an error, check your `.env` variables and try again. This prints everything in plain text, so don't share the output with anyone!

### Guides
More detailed guides for some of the difficult setups:
- [Discord Bot Setup](guides/discordBot.md)
- [Schwab 2FA Setup](guides/schwabSetup.md)

## Contributing
Found or fixed a bug? Have a feature request? Want to add support for a new brokerage? Feel free to open an issue or pull request!

Is someone selling a ripoff of this bot? (Looking at you OSU freshmen). Get it from here and contribute to open source!

Like what you see? Feel free to support me on Ko-Fi! 

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/X8X6LFCI0)

## DISCLAIMER
DISCLAIMER: I am not a financial advisor and not affiliated with any of the brokerages listed below. Use this tool at your own risk. I am not responsible for any losses or damages you may incur by using this project. This tool is provided as-is with no warranty.

## Supported brokerages:

All brokers: separate account credentials with a colon (":"). For example, `ALLY_USERNAME:ALLY_PASSWORD`. Separate multiple logins with the same broker with a comma (","). For example, `ALLY_USERNAME:ALLY_PASSWORD,ALLY_USERNAME2:ALLY_PASSWORD2`.

For Selenium-based brokers, you can optionally set the webdriver version by setting `WEBDRIVER_VERSION` in your `.env` file. For example, `WEBDRIVER_VERSION=114.0.5735.90`. This only applies to the CLI tool, not the Discord bot.

### Ally
Made using [PyAlly](https://github.com/alienbrett/PyAlly). Go give them a ⭐

Required `.env` variables:
- `ALLY_CONSUMER_KEY`
- `ALLY_CONSUMER_SECRET`
- `ALLY_OAUTH_TOKEN`
- `ALLY_OAUTH_SECRET`
- `ALLY_ACCOUNT_NUMBERS`

`.env` file format:
- `ALLY=ALLY_CONSUMER_KEY:ALLY_CONSUMER_SECRET:ALLY_OAUTH_TOKEN:ALLY_OAUTH_SECRET`
- `ALLY_ACCOUNT_NUMBERS=ALLY_ACCOUNT_NUMBER1:ALLY_ACCOUNT_NUMBER2`

To get these, follow [these instructions](https://alienbrett.github.io/PyAlly/installing.html#get-the-library).

### Fidelity
Made by yours truly using Selenium (and many hours of web scraping).

Required `.env` variables:
- `FIDELITY_USERNAME`
- `FIDELITY_PASSWORD`

`.env` file format:
- `FIDELITY=FIDELITY_USERNAME:FIDELITY_PASSWORD`

### Robinhood
Made using [robin_stocks](https://github.com/jmfernandes/robin_stocks). Go give them a ⭐

Required `.env` variables:
- `ROBINHOOD_USERNAME`
- `ROBINHOOD_PASSWORD`
- `ROBINHOOD_TOTP` (If 2fa enabled, else NA)
- `ROBINHOOD_IRA_NUMBERS` (If you want to use your IRA account, else NA. Separate multiple IRA numbers with commas)

`.env` file format:
- With 2fa: `ROBINHOOD=ROBINHOOD_USERNAME:ROBINHOOD_PASSWORD:ROBINHOOD_TOTP:ROBINHOOD_IRA_1:ROBINHOOD_IRA_2`
- Without 2fa: `ROBINHOOD=ROBINHOOD_USERNAME:ROBINHOOD_PASSWORD:NA:ROBINHOOD_IRA_1:ROBINHOOD_IRA_2`

If you don't have an IRA account or only have one, then you can omit the last field or set it to NA.

Configuring 2fa can be tricky, read the TOTP section [here](https://github.com/jmfernandes/robin_stocks/blob/master/Robinhood.rst).

To get your IRA numbers, check your monthly statement, or tap the menu button in the Robinhood app and go to `Investing`.

### Schwab
Made using the [schwab-api](https://github.com/itsjafer/schwab-api). Go give them a ⭐

Required `.env` variables:
- `SCHWAB_USERNAME`
- `SCHWAB_PASSWORD`
- `SCHWAB_TOTP_SECRET` (If 2fa is enabled, else NA)

`.env` file format:
- With 2fa: `SCHWAB=SCHWAB_USERNAME:SCHWAB_PASSWORD:SCHWAB_TOTP_SECRET`
- Without 2fa: `SCHWAB=SCHWAB_USERNAME:SCHWAB_PASSWORD:NA`

To get your TOTP secret, follow this [guide](guides/schwabSetup.md).

### Tradier
Made by yours truly using the official [Tradier API](https://documentation.tradier.com/brokerage-api/trading/getting-started). Consider giving me a ⭐

Required `.env` variables:
- `TRADIER_ACCESS_TOKEN`

`.env` file format:
- `TRADIER=TRADIER_ACCESS_TOKEN`

To get your access token, go to your [Tradier API settings](https://dash.tradier.com/settings/api).

### Tastytrade
Made by [MaxxRK](https://github.com/MaxxRK/) using the [tastytrade-api](https://github.com/tastyware/tastytrade). Go give them a ⭐

Required `.env` variables:
- `TASTYTRADE_USERNAME`
- `TASTYTRADE_PASSWORD`

`.env` file format:
- `TASTYTRADE=TASTYTRADE_USERNAME:TASTYTRADE_PASSWORD`

### Webull
Made using the [webull](https://github.com/tedchou12/webull) library. Go give them a ⭐

Required `.env` variables:
- `WEBULL_USERNAME`
- `WEBULL_PASSWORD`
- `WEBULL_ACCESS_TOKEN`
- `WEBULL_TRADING_PIN`

`.env` file format:
- `WEBULL=WEBULL_USERNAME:WEBULL_PASSWORD:WEBULL_ACCESS_TOKEN:WEBULL_TRADING_PIN`

To get your access token, follow this [guide](guides/webullSetup.md).

### Maybe future brokerages
#### Chase
I will be signing up for a Chase account soon, and I have heard that it is possible, so I will be looking into it soon.
#### Firstrade
In progress, coming soon.
#### SoFi
Login requires SMS 2fa, and I'm not sure how to do that automatically.
#### Vanguard
Will be added using Selenium just like Fidelity. I found this [vanguard-api](https://github.com/rikonor/vanguard-api), but it failed when I ran it.
#### Public
Same as Webull and SoFi.
### Never working brokerages
#### Stash
Why.
