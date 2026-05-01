# Usage

To buy and sell stocks, use this command:

`<prefix> <action> <amount> <ticker> <accounts> <dry>`

(Parameter explanation below)

For example, to buy 1 AAPL in all accounts:

`<prefix> buy 1 AAPL all false`

For a dry run of the above command in Robinhood only:

`<prefix> buy 1 AAPL robinhood true`

For a real run on Fidelity and Robinhood, but not Schwab:

`<prefix> buy 1 AAPL fidelity,robinhood not schwab false`

For a real run on Fidelity and Robinhood but not Schwab buying both AAPL and GOOG:

`<prefix> buy 1 AAPL,GOOG fidelity,robinhood not schwab false`

To check your account holdings:

`<prefix> holdings <accounts>`

For example, to check your account holdings on Chase and Vanguard, but not Robinhood:

`<prefix> holdings chase,vanguard not robinhood`

To restart the Discord bot:

`!restart` (without appending `!rsa` or prefix)

For help:

`!help` (without appending `!rsa` or prefix)

### Parameters Explanation ⚙️
- `<prefix>`: string, The prefix for the command. For the Discord bot, this is `!rsa`. For the CLI tool, this is `auto_rsa_bot`.
- `<action>`: string, "buy" or "sell"
- `<amount>`: integer, Amount to buy or sell.
- `<ticker>`: string, The stock ticker to buy or sell. Separate multiple tickers with commas and no spaces.
- `<accounts>`: string, What brokerage to run command in (robinhood, schwab, etc, or all). Separate multiple brokerages with commas and no spaces.
- `<not accounts>`: string proceeding `not`, What brokerages to exclude from command. Separate multiple brokerages with commas and no spaces.
- `<dry>`: boolean, Whether to run in `dry` mode (in which no transactions are made. Useful for testing). Set to `True`, `False`, or just write `dry` for`True`. Defaults to `True`, so if you want to run a real transaction, you must set this explicitly.

Note: There are two special keywords you can use when specifying accounts: `all` and `day1`. `all` will use every account that you have set up. `day1` will use "day 1" brokers, which are:
- BBAE
- Chase
- DSPAC
- Fennel
- Firstrade
- Public
- Schwab
- SoFi
- Tastytrade
- Tradier
- Webull

This is useful for brokers that provide quick turnaround times, hence the nickname "day 1".
A couple other keywords that can be used:
- `most`: will use every account you have setup except for vanguard.
- `fast`: will use every "day 1" broker + robinhood.
