## How to Setup the Discord Bot
In order to use this bot in Discord, you have to create a bot account and invite it to your server. This guide will show you how to do that.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click `New Application`.
2. Enter a name for your bot, like `AutoRSA` and click `Create`.
3. Click on `Bot` in the left sidebar, then give it a name and profile picture if you want.
4. Disable `Public Bot`.
5. Under `Privileged Gateway Intents`, enable `Message Content Intent`.
4. Scroll down to `Bot Permissions` and select `Send Messages`.
5. Click on `OAuth2` in the left sidebar, then scroll down to `Scopes` and select `bot`.
6. Scroll down to `Bot Permissions` and select `Send Messages`.
7. Copy the link in the `Scopes` section and paste it into your browser. Select the server you want to add the bot to and click `Authorize`.
8. Click on `Bot` in the left sidebar. Under `Token`, click `Reset Token`. Copy the new token and paste it into your `.env` file as `DISCORD_TOKEN`.
9. To get the Channel ID, turn on `Developer Mode` in Discord's settings, then right click on the channel and click `Copy ID`. Paste the ID into your `.env` file as `DISCORD_CHANNEL`.

If you need a more visual guide, one user found this [guide](https://www.writebots.com/discord-bot-token/) helpful.