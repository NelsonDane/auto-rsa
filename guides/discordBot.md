## How to Setup the Discord Bot
In order to use this bot in Discord, you have to create a bot account and invite it to your server. This guide will show you how to do that.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click `New Application`.
2. Enter a name for your bot, like `AutoRSA` and click `Create.
3. Click on `Installation` in the left sidebar, then uncheck `Guild Install` on the `Installation Contexts`.
4. Click on `Bot` in the left sidebar, then give it a name and profile picture if you want.
5. Disable `Public Bot`.
6. Under `Privileged Gateway Intents`, enable `Message Content Intent`.
7. Click on `OAuth2` in the left sidebar, then `URL Generator`. Then scroll down to `OAuth2 URL Generator`. 
8. Under `Scopes` select `bot`. Then underneath that in `Bot Permissions` select `Send Messages` and `Read Message History`.
9. Copy the link in the `Scopes` section and paste it into your browser. Select the server you want to add the bot to and click `Authorize`.
10. Click on `Bot` in the left sidebar. Under `Token`, click `Reset Token`. Copy the new token and paste it into your `.env` file as `DISCORD_TOKEN`.
11. To get the Channel ID, go to `Advanced` in Discord settings, then turn on `Developer Mode`. Then right click on the channel for the bot and click `Copy ID`. Paste the ID into your `.env` file as `DISCORD_CHANNEL`. If you want to turn off `Developer Mode`, you can do so, but it isn't necessary.

If you need a more visual guide, one user found [this guide](https://www.writebots.com/discord-bot-token/) helpful.
