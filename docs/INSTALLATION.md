# Installation
There are two ways to use this program: as a Discord bot or as a CLI tool. The setup instructions will be a little different depending on which method you choose. However, both methods require the same pre-setup steps, and the same `.env` file format.

### Env Setup
1. Copy the `.env.example` file to a new file called `.env`:

#### MacOS & Linux
```bash
cp .env.example .env
```

#### Windows
```powershell
copy .env.example .env
```

2. Fill in the `.env` file with your brokerage credentials. See the [Supported Brokerages](#-supported-brokerages-) section for more information.

Now follow the instructions for either the Discord Bot or CLI Tool. Once setup is complete, see the [Usage](#-usage-) section for how to use the program.

### Discord Bot Installation
To create your Discord bot and get your `DISCORD_TOKEN` for your `.env`, follow this [guide](docs/discordBot.md).

There are two ways to run the Discord bot: using Docker or running the Python script. When running the bot using the Python script, the bot will only be online when the script is running. With Docker, the bot will run in the background, restarting and updating automatically.

### Discord Bot: Docker
1. Add `DISCORD_TOKEN` and `DISCORD_CHANNEL` to your `.env` file.
2. Create the container using the provided [docker-compose.yml](docker-compose.yml) file:
```bash
docker compose up -d
```
3. The bot should appear online in Discord (You can also do `!ping` to check).

Docker Note: If you make any changes to your `.env` file, you will need to restart the container by running `docker-compose up -d` again. The bot will also automatically stay up to date thanks to the included [Watchtower](https://containrrr.dev/watchtower/).

### Discord Bot: Python Script
1. Install Python 3.12 or higher
2. Create a Python virtual environment:
```bash
python -m venv autorsa-venv
```
4. Activate the virtual environment:
#### MacOS & Linux
```bash
source ./autorsa-venv/bin/activate
```
#### Windows
```powershell
.\autorsa-venv\Scripts\activate
```
You should see `(autorsa-venv)` in your terminal prompt now. You will need to activate this virtual environment every time you close and reopen your terminal.

4. Install the package:
```bash
pip install auto_rsa_bot
```
5. Install Playwright's dependencies:
```bash
playwright install
```
6. Add `DISCORD_TOKEN` and `DISCORD_CHANNEL` to your `.env` file.
7. Start the bot using the following command:
```bash
auto_rsa_bot discord
```
8. The bot should appear online in Discord (You can also do `!ping` to check).

### CLI Tool Installation 💻
To run the CLI tool, follow these steps:
1. Install Python 3.12 or higher
2. Create a Python virtual environment:
```bash
python -m venv autorsa-venv
```
3. Activate the virtual environment:
#### MacOS & Linux
```bash
source ./autorsa-venv/bin/activate
```
#### Windows
```powershell
.\autorsa-venv\Scripts\activate
```
You should see `(autorsa-venv)` in your terminal prompt now. You will need to activate this virtual environment every time you close and reopen your terminal.

4. Install the package:
```bash
pip install auto_rsa_bot
```
5. Run the script using `auto_rsa_bot`. It should say that no arguments were given, then exit. This is expected, and means everything was installed and set up correctly.
