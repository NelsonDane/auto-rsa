# AutoRSA
## Discord Bot and CLI Tool
A CLI tool and Discord bot to buy, sell, and monitor holdings across multiple brokerage accounts!

<p>
<img src="https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54"/>
<img src="https://img.shields.io/badge/-selenium-%43B02A?style=for-the-badge&logo=selenium&logoColor=white"/>
<img src="https://img.shields.io/badge/-discord.py-%232c2f33?style=for-the-badge&logo=discord&logoColor=white"/>
<img src="https://img.shields.io/badge/-docker-%232c2f33?style=for-the-badge&logo=docker&logoColor=white"/>
</p>

This program uses APIs to interface with your brokerages. When available, official APIs are always used. If an official API is not available, then a third-party API is used. As a last resort, Selenium or Playwright Stealth are used to automate the browser.

## DISCLAIMER
DISCLAIMER: I am not a financial advisor and not affiliated with any of the brokerages listed below. Use this tool at your own risk. I am not responsible for any losses or damages you may incur by using this project. This tool is provided as-is with no warranty.

## Having an Issue?
I am not responding to issues on this repository. If you have an issue, please Sponsor me below and I will help you directly on Discord (for Sponsors and Contributors only).

[![Sponsor](https://img.shields.io/badge/sponsor-30363D?style=for-the-badge&logo=GitHub-Sponsors&logoColor=#white)](https://github.com/sponsors/NelsonDane)
[![ko-fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white
)](https://ko-fi.com/X8X6LFCI0)

However, if you fix the issue yourself and would like to share, please submit a pull request and I will review it. If accepted, you can access the Discord server for free.

## Contributing
Want to contribute? That's awesome! Check out the [Contributing Guide](CONTRIBUTING.md) for more information.

## Installation
See the [Installation Guide](docs/INSTALLATION.md) for detailed installation instructions.

## Usage
See the [Usage Guide](docs/USAGE.md) for detailed usage instructions.

## Supported brokerages
While the project was created by me, lots of work has been put in by the community to support and fix various brokerages. It wouldn't be possible without them, so go give them a ⭐!

| Brokerage | Created by | Source Repo | API Type | Fast | Day 1 |
| --- | --- | --- | --- | --- | --- |
| [BBAE](https://www.bbae.com/) | [@ImNotOssy](https://github.com/ImNotOssy) | [BBAE_investing_API](https://github.com/ImNotOssy/BBAE_investing_API) | Unofficial Requests | ✅ | ✅ |
| [Chase](https://www.chase.com/) | [@MaxxRK](https://github.com/MaxxRK/) | [chaseinvest-api](https://github.com/MaxxRK/chaseinvest-api) | Unofficial Requests | ✅ | ✅ |
| [DSPAC](https://www.dspac.com/) | [@ImNotOssy](https://github.com/ImNotOssy) | [dSPAC_investing_API](https://github.com/ImNotOssy/dSPAC_investing_API) | Unofficial Requests | ✅ | ✅ |
| [Fennel](https://fennel.com/) | [@NelsonDane](https://github.com/NelsonDane) | [fennel-invest-api](https://github.com/NelsonDane/fennel-invest-api) | Official API | ✅ | ✅ |
| [Fidelity](https://www.fidelity.com/) | [@kennyboy106](https://github.com/kennyboy106) | [fidelity-api](https://github.com/kennyboy106/fidelity-api) | Unofficial Playwright | ❌ | ❌ |
| [Firstrade](https://www.firstrade.com/) | [@MaxxRK](https://github.com/MaxxRK/) | [firstrade-api](https://github.com/MaxxRK/firstrade-api) | Unofficial Requests | ✅ | ✅ |
| [Public](https://public.com/) | [@PublicDotCom](https://github.com/PublicDotCom) | [publicdotcom-py](https://github.com/PublicDotCom/publicdotcom-py) | Official API Package | ✅ | ✅ |
| [Robinhood](https://robinhood.com/) | [@jmfernandes](https://github.com/jmfernandes) | [robin_stocks](https://github.com/jmfernandes/robin_stocks) | Unofficial Requests | ✅ | ❌ |
| [Schwab](https://www.schwab.com/) | [@itsjafer](https://github.com/itsjafer) | [schwab-api](https://github.com/itsjafer/schwab-api) | Unofficial Playwright | ✅ | ✅ |
| [SoFi](https://www.sofi.com/) | [@ImNotOssy](https://github.com/ImNotOssy) | Repo Unique | Unofficial [NoDriver](https://github.com/ultrafunkamsterdam/nodriver) | ✅ | ✅ |
| [Tastytrade](https://tastytrade.com/) | [@MaxxRK](https://github.com/MaxxRK/) | [tastytrade](https://github.com/tastyware/tastytrade) | Unofficial Requests | ✅ | ✅ |
| [Tornado](https://tornado.com/) | [@ImNotOssy](https://github.com/ImNotOssy) | Repo Unique | Unofficial Selenium | ❌ | ❌ |
| [Tradier](https://tradier.com/) | [@NelsonDane](https://github.com/NelsonDane) | [Tradier API](https://documentation.tradier.com/brokerage-api/trading/getting-started) | Official Requests | ✅ | ✅ |
| [Vanguard](https://www.vanguard.com/) | [@MaxxRK](https://github.com/MaxxRK/) | [vanguard-api](https://github.com/MaxxRK/vanguard-api) | Unofficial Requests | ❌ | ❌ |
| [Webull](https://www.webull.com/) | [@tedchou12](https://github.com/tedchou12) | [webull](https://github.com/tedchou12/webull) | Unofficial Requests | ✅ | ✅ |
| [Wells Fargo](https://www.wellsfargo.com/) | [@PZES](https://github.com/PZES) | Repo Unique | Unofficial Selenium | ❌ | ❌ |

## Brokerage Setup Guides
See the [Brokerage Setup Guides](docs/BROKERAGES.md) for detailed setup instructions for each brokerage.
