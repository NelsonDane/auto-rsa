# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import os
import sys
from time import sleep
from dotenv import load_dotenv
# Custom API libraries
from allyAPI import *
#from fidelityAPI import *
from robinhoodAPI import *
from schwabAPI import *
from webullAPI import *
from tradierAPI import *

# Stock to buy (TODO: make this a parameter somehow)
wanted_action = "Sell"
wanted_stock = "STAF"
wanted_amoount = 1
wanted_time = "Day"
wanted_price = "Market"
DRY = True

# Initialize .env file
load_dotenv()

# Initialize Accounts
print("==========================================================")
print("Initializing Accounts...")
print("==========================================================")
print()
ally_account = ally_init()
print()
#fidelity_init(fidelity_user, fidelity_password)
#print()
robinhood = robinhood_init()
print()
schwab = schwab_init()
print()
webull_account = webull_init()
print()
tradier = tradier_init()
print()

# # Buy/Sell stock on each account
# # Shut up, grammar is important smh
if wanted_amoount > 1:
    grammar = "shares"
else:
    grammar = "share"
print("==========================================================")
print(f"Order: {wanted_action} {wanted_amoount} {grammar} of {wanted_stock} on each account")
print("==========================================================")
print()
# Ally
ally_transaction(ally_account, wanted_action, wanted_stock, wanted_amoount, wanted_price, wanted_time, DRY)
# Robinhood
robinhood_transaction(robinhood, wanted_action, wanted_stock, wanted_amoount, wanted_price, wanted_time, DRY)
# Schwab
schwab_transaction(schwab, wanted_action, wanted_stock, wanted_amoount, wanted_price, wanted_time, DRY)
# Webull
webull_transaction(webull_account, wanted_action, wanted_stock, wanted_amoount, wanted_price, wanted_time, DRY)
# Tradier
tradier_transaction(tradier, wanted_action, wanted_stock, wanted_amoount, wanted_price, wanted_time, DRY)