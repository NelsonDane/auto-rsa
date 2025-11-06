"""Temp entrypoint for transitioning."""

import sys

from src.cli import rsa_main

if __name__ == "__main__":
    # Pass import args through to cli main
    rsa_main(sys.argv[1:])
