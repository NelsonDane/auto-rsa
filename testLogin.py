# Nelson Dane
# Script to check auto rsa logins
# Run this to make sure the accounts successfully log in

# Custom API libraries
from allyAPI import *
from fidelityAPI import *
from seleniumAPI import *
from robinhoodAPI import *
from schwabAPI import *
from webullAPI import *
from tradierAPI import *
from tastyAPI import *

# Initialize .env file
load_dotenv()

# Check whether to show env variables
if len(sys.argv) > 1 and sys.argv[1] == "show":
    show_env = True
else:
    show_env = False

# Check for environment variables
# Discord
if os.environ.get("DISCORD_TOKEN", None) is None:
    print(f"Discord token not found")
else:
    print(f"Discord token found {os.environ.get('DISCORD_TOKEN', None) if show_env else ''}")
if os.environ.get("DISCORD_CHANNEL", None) is None:
    print(f"Discord channel not found")
else:
    print(f"Discord channel found {os.environ.get('DISCORD_CHANNEL', None) if show_env else ''}")
# Ally
if os.environ.get("ALLY_CONSUMER_KEY", None) is None:
    print(f"Ally consumer key not found")
else:
    print(f"Ally consumer key found {os.environ.get('ALLY_CONSUMER_KEY', None) if show_env else ''}")
if os.environ.get("ALLY_CONSUMER_SECRET", None) is None:
    print(f"Ally consumer secret not found")
else:
    print(f"Ally consumer secret found {os.environ.get('ALLY_CONSUMER_SECRET', None) if show_env else ''}")
if os.environ.get("ALLY_OAUTH_TOKEN", None) is None:
    print(f"Ally oauth token not found")
else:
    print(f"Ally oauth token found {os.environ.get('ALLY_OAUTH_TOKEN', None) if show_env else ''}")
if os.environ.get("ALLY_OAUTH_SECRET", None) is None:
    print(f"Ally oauth secret not found")
else:
    print(f"Ally oauth secret found {os.environ.get('ALLY_OAUTH_SECRET', None) if show_env else ''}")
# Fidelity
if os.environ.get("FIDELITY_USERNAME", None) is None:
    print(f"Fidelity username not found")
else:
    print(f"Fidelity username found {os.environ.get('FIDELITY_USERNAME', None) if show_env else ''}")
if os.environ.get("FIDELITY_PASSWORD", None) is None:
    print(f"Fidelity password not found")
else:
    print(f"Fidelity password found {os.environ.get('FIDELITY_PASSWORD', None) if show_env else ''}")
# Robinhood
if os.environ.get("ROBINHOOD_USERNAME", None) is None:
    print(f"Robinhood username not found")
else:
    print(f"Robinhood username found {os.environ.get('ROBINHOOD_USERNAME', None) if show_env else ''}")
if os.environ.get("ROBINHOOD_PASSWORD", None) is None:
    print(f"Robinhood password not found")
else:
    print(f"Robinhood password found {os.environ.get('ROBINHOOD_PASSWORD', None) if show_env else ''}")
if os.environ.get("ROBINHOOD_TOTP", None) is None:
    print(f"Robinhood totp not found")
else:
    print(f"Robinhood totp found {os.environ.get('ROBINHOOD_TOTP', None) if show_env else ''}")
# Schwab
if os.environ.get("SCHWAB_USERNAME", None) is None:
    print(f"Schwab username not found")
else:
    print(f"Schwab username found {os.environ.get('SCHWAB_USERNAME', None) if show_env else ''}")
if os.environ.get("SCHWAB_PASSWORD", None) is None:
    print(f"Schwab password not found")
else:
    print(f"Schwab password found {os.environ.get('SCHWAB_PASSWORD', None) if show_env else ''}")
if os.environ.get("SCHWAB_TOTP_SECRET", None) is None:
    print(f"Schwab totp secret not found")
else:
    print(f"Schwab totp secret found {os.environ.get('SCHWAB_TOTP_SECRET', None) if show_env else ''}")
# Webull
if os.environ.get("WEBULL_USERNAME", None) is None:
    print(f"Webull username not found")
else:
    print(f"Webull username found {os.environ.get('WEBULL_USERNAME', None) if show_env else ''}")
if os.environ.get("WEBULL_PASSWORD", None) is None:
    print(f"Webull password not found")
else:
    print(f"Webull password found {os.environ.get('WEBULL_PASSWORD', None) if show_env else ''}")
if os.environ.get("WEBULL_TRADE_PIN", None) is None:
    print(f"Webull trade pin not found")
else:
    print(f"Webull trade pin found {os.environ.get('WEBULL_TRADE_PIN', None) if show_env else ''}")
# Tradier
if os.environ.get("TRADIER_TOKEN", None) is None:
    print(f"Tradier token not found")
else:
    print(f"Tradier token found {os.environ.get('TRADIER_TOKEN', None) if show_env else ''}")
# Tastytrade
if os.environ.get("TASTYTRADE_USERNAME", None) is None:
    print(f"Tastytrade username not found")
else:
    print(f"Tastytrade username found {os.environ.get('TASTYTRADE_USERNAME', None) if show_env else ''}")
if os.environ.get("TASTYTRADE_PASSWORD", None) is None:
    print(f"Tastytrade password not found")
else:
    print(f"Tastytrade password found {os.environ.get('TASTYTRADE_PASSWORD', None) if show_env else ''}")

# Check each account
print("==========================================================")
print("Checking Accounts...")
print("==========================================================")
print()
ally_account = ally_init()
print()
fidelity_account = fidelity_init()
killDriver(fidelity_account)
print()
robinhood = robinhood_init()
print()
schwab = schwab_init()
print()
# webull_account = webull_init()
# if webull_account is not None:
# print()
tradier = tradier_init()
print()
tastytrade = tastytrade_init()
# Print results
print("==========================================================")
print("All checks complete")
print("==========================================================")
print()
