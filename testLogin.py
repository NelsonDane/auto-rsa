# Nelson Dane
# Script to check auto rsa logins
# Run this to make sure the accounts successfully log in

# Custom API libraries
from allyAPI import *
from fidelityAPI import *
from seleniumAPI import *
from robinhoodAPI import *
from schwabAPI import *
from tradierAPI import *
from tastyAPI import *

# Initialize .env file
load_dotenv()

# Check for environment variables
# Discord
if os.environ.get("DISCORD_TOKEN", None) is None:
    print(f"Discord token not found")
else:
    print(f"Discord token found {os.environ.get('DISCORD_TOKEN')}")
if os.environ.get("DISCORD_CHANNEL", None) is None:
    print(f"Discord channel not found")
else:
    print(f"Discord channel found {os.environ.get('DISCORD_CHANNEL')}")
# Ally
if os.environ.get("ALLY_CONSUMER_KEY", None) is None:
    print(f"Ally consumer key not found")
else:
    print(f"Ally consumer key found {os.environ.get('ALLY_CONSUMER_KEY')}")
if os.environ.get("ALLY_CONSUMER_SECRET", None) is None:
    print(f"Ally consumer secret not found")
else:
    print(
        f"Ally consumer secret found {os.environ.get('ALLY_CONSUMER_SECRET')}")
if os.environ.get("ALLY_OAUTH_TOKEN", None) is None:
    print(f"Ally oauth token not found")
else:
    print(f"Ally oauth token found {os.environ.get('ALLY_OAUTH_TOKEN')}")
if os.environ.get("ALLY_OAUTH_SECRET", None) is None:
    print(f"Ally oauth secret not found")
else:
    print(f"Ally oauth secret found {os.environ.get('ALLY_OAUTH_SECRET')}")
# Fidelity
if os.environ.get("FIDELITY_USERNAME", None) is None:
    print(f"Fidelity username not found")
else:
    print(f"Fidelity username found {os.environ.get('FIDELITY_USERNAME')}")
if os.environ.get("FIDELITY_PASSWORD", None) is None:
    print(f"Fidelity password not found")
else:
    print(f"Fidelity password found {os.environ.get('FIDELITY_PASSWORD')}")
# Robinhood
if os.environ.get("ROBINHOOD_USERNAME", None) is None:
    print(f"Robinhood username not found")
else:
    print(f"Robinhood username found {os.environ.get('ROBINHOOD_USERNAME')}")
if os.environ.get("ROBINHOOD_PASSWORD", None) is None:
    print(f"Robinhood password not found")
else:
    print(f"Robinhood password found {os.environ.get('ROBINHOOD_PASSWORD')}")
if os.environ.get("ROBINHOOD_TOTP", None) is None:
    print(f"Robinhood totp not found")
else:
    print(f"Robinhood totp found {os.environ.get('ROBINHOOD_TOTP')}")
# Schwab
if os.environ.get("SCHWAB_USERNAME", None) is None:
    print(f"Schwab username not found")
else:
    print(f"Schwab username found {os.environ.get('SCHWAB_USERNAME')}")
if os.environ.get("SCHWAB_PASSWORD", None) is None:
    print(f"Schwab password not found")
else:
    print(f"Schwab password found {os.environ.get('SCHWAB_PASSWORD')}")
if os.environ.get("SCHWAB_TOTP_SECRET", None) is None:
    print(f"Schwab totp secret not found")
else:
    print(f"Schwab totp secret found {os.environ.get('SCHWAB_TOTP_SECRET')}")
# Tradier
if os.environ.get("TRADIER_TOKEN", None) is None:
    print(f"Tradier token not found")
else:
    print(f"Tradier token found {os.environ.get('TRADIER_TOKEN')}")
# Tastytrade
if os.environ.get("TASTYTRADE_USERNAME", None) is None:
    print(f"Tastytrade username not found")
else:
    print(f"Tastytrade username found {os.environ.get('TASTYTRADE_USERNAME')}")
if os.environ.get("TASTYTRADE_PASSWORD", None) is None:
    print(f"Tastytrade password not found")
else:
    print(f"Tastytrade password found {os.environ.get('TASTYTRADE_PASSWORD')}")

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
print("==========================================================")
print("All checks complete")
print("==========================================================")
print()
