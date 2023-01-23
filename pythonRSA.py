# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import sys
import asyncio
from dotenv import load_dotenv
# Custom API libraries
from autoRSA import *
from allyAPI import *
from fidelityAPI import *
from robinhoodAPI import *
from schwabAPI import *
from webullAPI import *
from tradierAPI import *

# List of supported and enabled brokerages
supported_brokerages = ["all", "ally", "fidelity", "robinhood", "rh", "schwab", "tradier"]
enabled_brokerages = []
AO = []

# Initialize .env file
load_dotenv()

# Get stock info from command line arguments
if len(sys.argv) == 1:
    print("Not enough arguments provided, please see the README for documentation.")
    sys.exit(1)
elif len(sys.argv) > 1 and sys.argv[1] != "holdings":
    wanted_action = sys.argv[1].lower()
    try:
        wanted_amount = int(sys.argv[2])
    except:
        if sys.argv[2] == "all":
            wanted_amount = "all"
        else:
            print("Error: Invalid amount")
            sys.exit(1)
    wanted_stock = sys.argv[3].upper()
    wanted_time = "day" # Only supports day for now
    wanted_price = "market" # Only supports market for now
    # Check if DRY mode is enabled   
    if ((sys.argv[4].lower()) == "dry" or (sys.argv[4].lower()) == "true") and not (sys.argv[4].lower() in supported_brokerages):
        DRY = True
        single_broker = "all"
    elif sys.argv[4].lower() in supported_brokerages:
        single_broker = sys.argv[4].lower()
    if len(sys.argv) > 5:
        if sys.argv[5].lower() == "dry" or sys.argv[5].lower() == "true":
            DRY = True
        else:
            DRY = False
    print(f"Action: {wanted_action}")
    print(f"Amount: {wanted_amount}")
    print(f"Stock: {wanted_stock}")
    print(f"Time: {wanted_time}")
    print(f"Price: {wanted_price}")
    print(f"Broker: {single_broker}")
    print(f"DRY: {DRY}")
    print()
    input("Press enter to continue...")
    print()
    should_get_holdings = False
elif len(sys.argv) == 3 and sys.argv[1] == "holdings":
    single_broker = sys.argv[2].lower()
    should_get_holdings = True
else:
    should_get_holdings = False

if single_broker == "all":
    # Initialize Accounts
    print("==========================================================")
    print("Initializing Accounts...")
    print("==========================================================")
    print()
    ally_account = ally_init()
    if ally_account is not None:
        AO.append(ally_account)
        enabled_brokerages.append("ally")
    print()
    fidelity_account = fidelity_init()
    if fidelity_account is not None:
        AO.append(fidelity_account)
        enabled_brokerages.append("fidelity")
    print()
    try:
        robinhood = robinhood_init()
        if robinhood is not None:
            AO.append(robinhood)
            enabled_brokerages.append("robinhood")
    except:
        print("Robinhood failed, retrying...")
        sleep(5)
        robinhood = robinhood_init()
        if robinhood is not None:
            AO.append(robinhood)
            enabled_brokerages.append("robinhood")
    print()
    schwab = schwab_init()
    if schwab is not None:
        AO.append(schwab)
        enabled_brokerages.append("schwab")
    print()
    # webull_account = webull_init()
    # if webull_account is not None:
    # print()
    tradier = tradier_init()
    if tradier is not None:
        AO.append(tradier)
        enabled_brokerages.append("tradier")
    print()
elif single_broker == "ally":
    ally_account = ally_init()
    if ally_account is not None:
        AO.append(ally_account)
        enabled_brokerages.append("ally")
    print()
elif single_broker == "fidelity":
    fidelity_account = fidelity_init()
    if fidelity_account is not None:
        AO.append(fidelity_account)
        enabled_brokerages.append("fidelity")
elif single_broker == "robinhood" or single_broker == "rh":
    try:
        robinhood = robinhood_init()
        if robinhood is not None:
            AO.append(robinhood)
            enabled_brokerages.append("robinhood")
    except:
        sleep(5)
        robinhood = robinhood_init()
        if robinhood is not None:
            AO.append(robinhood)
            enabled_brokerages.append("robinhood")
    print()
elif single_broker == "schwab":
    schwab = schwab_init()
    if schwab is not None:
        AO = [schwab]
        enabled_brokerages = ["schwab"]
    print()
elif single_broker == "webull" or single_broker == "wb":
    webull_account = webull_init()
    if webull_account is not None:
        AO = [webull_account]
        enabled_brokerages = ["webull"]
    print()
elif single_broker == "tradier":
    tradier = tradier_init()
    if tradier is not None:
        AO = [tradier]
        enabled_brokerages = ["tradier"]
    print()
else:
    print("Error: Invalid broker")
    sys.exit(1)

# If get holdings, get them
if should_get_holdings:
    try:
        if single_broker == "all":
            for i, a in enumerate(AO):
                print(f"Getting holdings for {enabled_brokerages[i]}...")
                asyncio.run(get_holdings(accountName=enabled_brokerages[i], AO=a))
        else:
            asyncio.run(get_holdings(accountName=single_broker, AO=AO[0]))
        sys.exit(0)
    except Exception as e:
        print(f"Error getting holdings: {e}")
        sys.exit(1)
# If run from the command line, run once and exit
# Run place order function then exit
try:
    if single_broker == "all":
        for i, a in enumerate(AO):
            asyncio.run(place_order(wanted_action, wanted_amount, wanted_stock, single_broker=enabled_brokerages[i], AO=a, DRY=DRY))
    else:
        asyncio.run(place_order(wanted_action, wanted_amount, wanted_stock, single_broker, AO=AO[0], DRY=DRY))
    sys.exit(0)
# If error, exit with error code
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)