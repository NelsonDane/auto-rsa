# autoRSA Discord Bot and CLI Tool
A CLI tool and Discord bot to buy and sell the same amount of stocks across multiple accounts!

## Discord Bot Installation
### Docker
View on [Docker Hub](https://hub.docker.com/repository/docker/nelsondane/auto-rsa)
1. Clone the repo and cd into it
2. Create a `.env` file for your brokerage variables, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
3. Just run `docker run --env-file ./.env -itd --restart unless-stopped --name rsa nelsondane/auto-rsa:latest`
4. The bot should appear online (You can also do `!ping` to check). See below for more command explanations.

### Always Running Python Script
Make sure python3-pip is installed
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables, and add your bot using `DISCORD_TOKEN` and `DISCORD_CHANNEL`
4. Run `python autoRSA.py` (See below for more command explanations)

## CLI Tool Installation
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables
2. Run the script using `python pythonRSA.py <action> <amount> <ticker> <account> <dry>` (See below for more parameter explanations)

## Usage
### Discord Bot
`Ping-Pong`: Once the bot is invited to your server, you can check that it's running by sending `!ping`, to which the bot should respond with `pong`

To buy and sell stocks, just send a message of this format in discord:

`!rsa <action> <amount> <ticker> <account> <dry>`

For example, to buy 1 STAF in all accounts:

`!rsa buy 1 STAF all false`

For a dry run of the above command in Robinhood only:

`!rsa buy 1 STAF robinhood true`

To check your account holdings:

`!holdings <account>`

To see when the market opens/closes:

`!market` or `!market_hours`

To restart the bot:

`!restart`

For help:

`!help`

### CLI Tool:
To buy and sell stocks, just this command when in the repo directory:

`python pythonRSA.py <action> <amount> <ticker> <account> <dry>`

For example, to buy 1 STAF in all accounts:

`python pythonRSA.py buy 1 STAF all false`

For a dry run of the above command in Robinhood only:

`python pythonRSA.py buy 1 STAF robinhood true`

To check individual account holdings:

`python pythonRSA.py holdings <account>`

### Parameters
- `<action>`: "buy" or "sell"
- `<amount>`: Amount to buy or sell. Must be an integer
- `<ticker>`: The stock ticker to buy or sell
- `<account>`: What brokerage to run command in (robinhood, schwab, etc, or all)
- `<dry>`: Whether to run in "dry" mode (in which no transactions are made, useful for testing). Set to True, False, or just write "dry" for True. Defaults to True, so if you want to run a real transaction, you must set this to False/dry.

## Supported brokerages:
### Ally
Made using [PyAlly](https://github.com/alienbrett/PyAlly). Go give them a ⭐

Required `.env` variables:
- ALLY_CONSUMER_KEY
- ALLY_CONSUMER_SECRET
- ALLY_OAUTH_TOKEN
- ALLY_OAUTH_SECRET
- ALLY_ACCOUNT_NBR

To get these, follow [these instructions](https://alienbrett.github.io/PyAlly/installing.html#get-the-library)
### Robinhood
Made using [robin_stocks](https://github.com/jmfernandes/robin_stocks). Go give them a ⭐

Required `.env` variables:
- ROBINHOOD_USERNAME
- ROBINHOOD_PASSWORD
- ROBINHOOD_TOTP: If 2fa enabled

Configuring 2fa can be tricky, read the TOTP section [here](https://github.com/jmfernandes/robin_stocks/blob/master/Robinhood.rst)
### Schwab
Made using [schwab-api](https://github.com/itsjafer/schwab-api). Go give them a ⭐

Required `.env` variables:
- SCHWAB_USERNAME=
- SCHWAB_PASSWORD=
- SCHWAB_TOTP_SECRET= (If 2fa is enabled)

To get your TOTP secret, use [this website by the api author](https://itsjafer.com/#/schwab)
### Tradier
Made by yours truly using the official [Tradier API](https://documentation.tradier.com/brokerage-api/trading/getting-started)

Required `.env` variables:
- TRADIER_ACCESS_TOKEN

To get your access token, go to your [Tradier API settings](https://dash.tradier.com/settings/api)
### Maybe future brokerages
#### Fidelity
No official or 3rd party APIs were found, so would have to create one from scratch using web scraping. (Kind of like these: [one](https://www.youtube.com/watch?v=PrSgKllqquA) [two](https://www.youtube.com/watch?v=CF5ItVde4lc&t=315s)).
#### Vanguard
Same as Fidelity. I found this [vanguard-api](https://github.com/rikonor/vanguard-api), but it failed when I ran it.
#### SoFi
No official or 3rd party APIs, but they do have a website. So same as Fidelity and Vanguard.
#### Webull
Not currently working since login is broken in [webull](https://github.com/tedchou12/webull). Go give them a ⭐ anyways.
### Never working brokerages
#### Public
No official or 3rd party APIs and no website to scrape (app only).
#### Stash
Why.
