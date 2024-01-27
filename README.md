# ✨ AutoRSA ✨ 
## Discord Bot and CLI Tool
A CLI tool and Discord bot to buy, sell, and monitor holdings across multiple accounts!

<p>
<img src="https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54"/>
<img src="https://img.shields.io/badge/-selenium-%43B02A?style=for-the-badge&logo=selenium&logoColor=white"/>
<img src="https://img.shields.io/badge/-discord.py-%232c2f33?style=for-the-badge&logo=discord&logoColor=white"/>
<img src="https://img.shields.io/badge/-docker-%232c2f33?style=for-the-badge&logo=docker&logoColor=white"/>
</p>

## ❓ What is RSA? ❓
You already know what Reverse Split Arbitrage is, that's not why you're here. If you do know what it is, then you know why a tool like this would be valuable. If you're a big player, even more so...

## 🤔 How Does It Work? 🤔
This program uses APIs to interface with your brokerages. When available, official APIs are always used. If an official API is not available, then a third-party API is used. As a last resort, Selenium or Playwright Stealth are used to automate the browser.

## 🤖 Discord Bot Installation 🤖
To create your Discord bot and get your `DISCORD_TOKEN`, follow this [guide](guides/discordBot.md).
### 🐳 Docker 🐳
1. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
2. Using the provided [docker-compose.yml](docker-compose.yml) file, run the command `docker compose up -d` inside the project directory.
3. The bot should appear online (You can also do `!ping` to check). 

### 🏃‍♂️ Always Running Python Script 🏃‍♀️
Make sure python3-pip is installed
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
4. Run `python autoRSA.py` (See below for more command explanations)

Note: If you are using Windows, you will need to install playwright manually. See [this guide](guides/playwrightWindows.md) for more information.

## 💻 CLI Tool Installation 💻
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables using [.env.example](.env.example) as a template.
4. Run the script using `python autoRSA.py` plus the command you want to run (See below for more command explanations)

Note: If you are using Windows, you will need to install playwright manually. See [this guide](guides/playwrightWindows.md) for more information.

## 👀 Usage 👀
If running as a Discord bot, append `!rsa` to the beginning of each command.
If running from the CLI Tool, append `python autoRSA.py` to the beginning of each command.

To buy and sell stocks, use this command:

`<action> <amount> <ticker> <accounts> <dry>`

For example, to buy 1 AAPL in all accounts:

`buy 1 AAPL all false`

For a dry run of the above command in Robinhood only:

`buy 1 AAPL robinhood true`

For a real run on Fidelity and Robinhood, but not Schwab:

`buy 1 AAPL fidelity,robinhood not schwab false`

For a real run on Fidelity and Robinhood but not Schwab buying both AAPL and GOOG:

`buy 1 AAPL,GOOG fidelity,robinhood not schwab false`

To check your account holdings:

`holdings <accounts>`

To restart the Discord bot:

`!restart` (without appending `!rsa`)

For help:

`!help` (without appending `!rsa`)

Note: There are two special keywords you can use when specifying accounts: `all` and `day1`. `all` will use every account that you have set up. `day1` will use "day 1" brokers, which are Robinhood, Schwab, Tastytrade, and Tradier. This is useful for brokers that provide quick turnaround times, hence the nickname "day 1".

### ⚙️ Parameters ⚙️
- `<action>`: string, "buy" or "sell"
- `<amount>`: integer, Amount to buy or sell.
- `<ticker>`: string, The stock ticker to buy or sell. Separate multiple tickers with commas and no spaces.
- `<accounts>`: string, What brokerage to run command in (robinhood, schwab, etc, or all). Separate multiple brokerages with commas and no spaces.
- `<not accounts>`: string proceeding `not`, What brokerages to exclude from command. Separate multiple brokerages with commas and no spaces.
- `<dry>`: boolean, Whether to run in `dry` mode (in which no transactions are made. Useful for testing). Set to `True`, `False`, or just write `dry` for`True`. Defaults to `True`, so if you want to run a real transaction, you must set this explicitly.

### 🗺️ Guides 🗺️
More detailed guides for some of the difficult setups:
- [Discord Bot Setup](guides/discordBot.md)
- [Schwab 2FA Setup](guides/schwabSetup.md)

## 🤝 Contributing 🤝
Found or fixed a bug? Have a feature request? Want to add support for a new brokerage? Feel free to open an issue or pull request!

Enjoying the project? Feel free to Sponsor me on GitHub or Ko-fi!

[![Sponsor](https://img.shields.io/badge/sponsor-30363D?style=for-the-badge&logo=GitHub-Sponsors&logoColor=#white)](https://github.com/sponsors/NelsonDane)
[![ko-fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white
)](https://ko-fi.com/X8X6LFCI0)

## 😳 DISCLAIMER 😳
DISCLAIMER: I am not a financial advisor and not affiliated with any of the brokerages listed below. Use this tool at your own risk. I am not responsible for any losses or damages you may incur by using this project. This tool is provided as-is with no warranty.

## 👍 Supported brokerages 👍

All brokers: separate account credentials with a colon (":"). For example, `SCHWAB_USERNAME:SCHWAB_PASSWORD`. Separate multiple logins with the same broker with a comma (","). For example, `SCHWAB_USERNAME:SCHWAB_PASSWORD,SCHWAB_USERNAME2:SCHWAB_PASSWORD2`.

#### Chase
Made by [MaxxRK](https://github.com/MaxxRK/) using the [chaseinvest-api](https://github.com/MaxxRK/chaseinvest-api). Go give them a ⭐
- `CHASE_USERNAME`
- `CHASE_PASSWORD`
- `CELL_PHONE_LAST_FOUR`

`.env` file format:
- `CHASE=CHASE_USERNAME:CHASE_PASSWORD:CELL_PHONE_LAST_FOUR`

### Fidelity
Made by yours truly using Selenium (and many hours of web scraping).

Required `.env` variables:
- `FIDELITY_USERNAME`
- `FIDELITY_PASSWORD`

`.env` file format:
- `FIDELITY=FIDELITY_USERNAME:FIDELITY_PASSWORD`

### Firstrade
Made by [MaxxRK](https://github.com/MaxxRK/) using the [firstrade-api](https://github.com/MaxxRK/firstrade-api). Go give them a ⭐

Required `.env` variables:
- `FIRSTRADE_USERNAME`
- `FIRSTRADE_PASSWORD`
- `FIRSTRADE_PIN`

`.env` file format:
- `FIRSTRADE=FIRSTRADE_USERNAME:FIRSTRADE_PASSWORD:FIRSTRADE_PIN`

### Public
Made by yours truly using using [public-invest-api](https://github.com/NelsonDane/public-invest-api). Consider giving me a ⭐

Required `.env` variables:
- `PUBLIC_USERNAME`
- `PUBLIC_PASSWORD`

`.env` file format:
- `PUBLIC=PUBLIC_USERNAME:PUBLIC_PASSWORD`

### Robinhood
Made using [robin_stocks](https://github.com/jmfernandes/robin_stocks). Go give them a ⭐

Required `.env` variables:
- `ROBINHOOD_USERNAME`
- `ROBINHOOD_PASSWORD`
- `ROBINHOOD_TOTP` (If 2fa enabled, else NA)

`.env` file format:
- With 2fa: `ROBINHOOD=ROBINHOOD_USERNAME:ROBINHOOD_PASSWORD:ROBINHOOD_TOTP`
- Without 2fa: `ROBINHOOD=ROBINHOOD_USERNAME:ROBINHOOD_PASSWORD:NA`

If you don't have an IRA account or only have one, then you can omit the last field or set it to NA.

Configuring 2fa can be tricky, read the TOTP section [here](https://github.com/jmfernandes/robin_stocks/blob/master/Robinhood.rst#with-mfa-entered-programmatically-from-time-based-one-time-password-totp).

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

Note 1: Think or Swim must be enabled on all accounts. To enable, go to `Trade` > `Trading Platforms` > `Learn how to enable thinkorswim`. Then press `Continue` and expand the `thinkorswim Access Agreement` and accept it. Then press `Continue` again. Then select the checkbox for all available accounts and press `Submit`. It may take a day or two for the accounts to be enabled.

Note 2: If you are using Windows, you may need to install playwright manually. See [this guide](guides/playwrightWindows.md) for more information.

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

### 🤷‍♂️ Maybe future brokerages 🤷‍♀️
#### Ally
Ally disabled their official API, so all Ally packages don't work. I am attempting to reverse engineer their API, which you can track [here](https://github.com/NelsonDane/ally-api). Once I get it working, I will add it to this project.
#### Vanguard
Will be added using Selenium just like Fidelity. I found this [vanguard-api](https://github.com/rikonor/vanguard-api), but it failed when I ran it.
#### SoFi
Login requires SMS 2fa, and I'm not sure how to do that automatically.
#### Webull
In progress on [develop-webull](https://github.com/NelsonDane/auto-rsa/pull/61). Stay tuned.
#### Public
In progress on [develop-public](https://github.com/NelsonDane/auto-rsa/pull/150). Stay tuned.
### 👎 Never working brokerages 👎
#### Stash
Why.
