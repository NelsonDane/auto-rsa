# auto-rsa CLI tool/Discord bot
A CLI tool and discord bot to buy the same amount of stocks in multiple accounts!

## Discord Bot Installation
### Docker
View on [Docker Hub](https://hub.docker.com/repository/docker/nelsondane/auto-rsa)
1. Clone the repo and cd into it
2. Create a `.env` file for your brokerage variables, and add your bot token using `DISCORD_TOKEN`
3. Build the image with `docker build -t rsa .`
4. Just run `docker run --env-file ./.env -it --restart unless-stopped --name rsa rsa`
5. The bot should appear online (You can also do `!ping`. Once bot is working, just enter CTRL-p then CTRL-q to exit gracefully, letting the bot run in the background. See below for command explanation

### Always Running Python Script
Make sure python3-pip is installed
1. Clone this repository and cd into it
2. Run `pip install -r requirements.txt`
3. Create a `.env` file for your brokerage variables, and add your bot token using `DISCORD_TOKEN`
4. Run 'python auto-rsa.py` (See below for command explanation)

## CLI Tool Installation
1. Follow the Always Running Python Script steps until Step 4
2. Run the script using `python3 auto-rsa.py <action> <amount> <ticker> <account> <dry>` (See below for parameter explanation)

## Usage
Ping-Pong: Once the bot is invited to your server, you can check that it's running by sending `!ping`, to which the bot should respond with `pong`

To buy and sell stocks, just send a message of this format in discord:
`!rsa <action> <amount> <ticker> <account> <dry>

### CLI Tool/Discord Bot Parameters explained:
- `!rsa`: command name (not in CLI)
- `<action>`: `buy` or `sell`
- `<amount>`: Amount to buy or sell. Must be an integer
- `<ticker>`: The stock ticker to buy or sell
- `<account>`: What brokerage to run it in (robinhood, schwab, or all)
- `<dry>`: Whether to run in "dry" mode (in which no transactions are made, useful for testing). Set to True, False, or just write "dry" for True
#### Discord bot:
For example, to buy 1 STAF in all accounts:
`!rsa buy 1 STAF all false`
For a dry run of the above command in Robinhood only:
`!rsa buy 1 STAF robinhood true`
To check individual account holdings:
`!holdings broker-name`
To see when the market opens/closes:
`!market`
To restart the bot:
`!restart`

After a few seconds, the bot will let you know if anything happened! (Hopefully)

#### CLI Tool:
For example, to buy 1 STAF in all accounts:
`python3 auto-rsa.py buy 1 STAF all false`
For a dry run of the above command in Robinhood only:
`python3 auto-rsa.py buy 1 STAF robinhood true`
To check individual account holdings:
`python3 auto-rsa.py holdings broker-name`

After a few seconds you should see some output in the terminal (Hopefully)


### Supported brokerages:
#### Ally
Made using [PyAlly](https://github.com/alienbrett/PyAlly). Go give them a ⭐

Required `.env` variables:
- ALLY_CONSUMER_KEY
- ALLY_CONSUMER_SECRET
- ALLY_OAUTH_TOKEN
- ALLY_OAUTH_SECRET
- ALLY_ACCOUNT_NBR

To get these, follow [these instructions](https://alienbrett.github.io/PyAlly/installing.html#get-the-library)
#### Robinhood
Made using [robin_stocks](https://github.com/jmfernandes/robin_stocks). Go give them a ⭐

Required `.env` variables:
- ROBINHOOD_USERNAME
- ROBINHOOD_PASSWORD
- ROBINHOOD_TOTP: If 2fa enabled

Configuring 2fa can be tricky, read the TOTP section [here](https://github.com/jmfernandes/robin_stocks/blob/master/Robinhood.rst)
#### Schwab
Made using [schwab-api](https://github.com/itsjafer/schwab-api). Go give them a ⭐

Required `.env` variables:
- SCHWAB_USERNAME=
- SCHWAB_PASSWORD=
- SCHWAB_TOTP_SECRET= If 2fa is enabled

To get your TOTP secret, use [this website by the api author](https://itsjafer.com/#/schwab)
#### Webull
Made using [webull](https://github.com/tedchou12/webull). Go give them a ⭐

Required `.env` variables:
- WEBULL_USERNAME
- WEBULL_PASSWORD
- WEBULL_TRADE_PIN

#### Tradier
Made by me using the official [Tradier API](https://documentation.tradier.com/brokerage-api/trading/getting-started)

Required `.env` variables:
- TRADIER_ACCESS_TOKEN

To get your access token, go to your [Tradier API settings](https://dash.tradier.com/settings/api)
### Maybe future brokerages
#### Fidelity
No official or 3rd party APIs were found, so would have to create one from scratch using web scraping. (Kind of like these [one](https://www.youtube.com/watch?v=PrSgKllqquA) [two](https://www.youtube.com/watch?v=CF5ItVde4lc&t=315s))
### Vanguard
Same as Fidelity. I found this [vanguard-api](https://github.com/rikonor/vanguard-api), but it failed when I ran it.

### Never working brokerages
#### Public
No official or 3rd party APIs, no website to scrape (app only)
#### SoFi
No official or 3rd party APIs, no website to scrape (app only)
#### Stash
Why
