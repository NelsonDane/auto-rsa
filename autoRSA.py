"""Temp entrypoint for transitioning."""

import sys
from time import sleep

from src.cli import rsa_main

if __name__ == "__main__":
    # Print warning
    print("==================================")
    print("WARNING: autoRSA.py is deprecated.")
    print("Please install the 'auto_rsa_bot' package. No more need to clone the repo!")
    print("Please see the README for more information.")
    print("==================================")
    sleep(10)
    # Pass import args through to cli main
    rsa_main(sys.argv[1:])
