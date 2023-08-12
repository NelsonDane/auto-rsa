# Nelson Dane
# Script to check auto rsa logins
# Run this to make sure the accounts successfully log in

# Standard libraries
import os

from dotenv import load_dotenv

# Custom API libraries
from allyAPI import ally_init
from fidelityAPI import fidelity_init
from robinhoodAPI import robinhood_init
from schwabAPI import schwab_init
from tastyAPI import tastytrade_init
from tradierAPI import tradier_init

# Initialize .env file
load_dotenv()

# Check for environment variables
# Discord
if os.environ.get("DISCORD_TOKEN") is None:
    print("DISCORD_TOKEN not found")
else:
    print(f"Discord token found {os.environ.get('DISCORD_TOKEN')}")
if os.environ.get("DISCORD_CHANNEL") is None:
    print("DISCORD_CHANNEL not found")
else:
    print(f"Discord channel found {os.environ.get('DISCORD_CHANNEL')}")
# Ally
if os.environ.get("ALLY") is None:
    print("ALLY not found")
else:
    print(f"ALLY found {os.environ.get('ALLY')}")
# Fidelity
if os.environ.get("FIDELITY") is None:
    print("FIDELITY not found")
else:
    print(f"FIDELITY found {os.environ.get('FIDELITY')}")
# Robinhood
if os.environ.get("ROBINHOOD") is None:
    print("ROBINHOOD not found")
else:
    print(f"ROBINHOOD found {os.environ.get('ROBINHOOD')}")
# Schwab
if os.environ.get("SCHWAB") is None:
    print("SCHWAB not found")
else:
    print(f"SCHWAB found {os.environ.get('SCHWAB')}")
# Tradier
if os.environ.get("TRADIER") is None:
    print("TRADIER not found")
else:
    print(f"TRADIER found {os.environ.get('TRADIER')}")
# Tastytrade
if os.environ.get("TASTYTRADE") is None:
    print("TASTYTRADE not found")
else:
    print(f"TASTYTRADE found {os.environ.get('TASTYTRADE')}")
print()

# Check each account
print("==========================================================")
print("Checking Accounts...")
print("==========================================================")
print()
ally_init()
print()
fidelity_init()
print()
robinhood_init()
print()
schwab_init()
print()
tradier_init()
print()
tastytrade_init()
# Print results
print()
print("==========================================================")
print("All checks complete")
print("==========================================================")
print()
