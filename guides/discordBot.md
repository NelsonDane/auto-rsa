## How to Setup the Discord Bot
In order to use this bot in Discord, you have to create a bot account. This guide will show you how to do that.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click `New Application`.
2. Enter a name for your bot, like `AutoRSA` and click `Create`.
3. Click on `Bot` in the left sidebar, then give it a name and profile picture if you want.
4. Under `Token`, click `Reset Token`. Copy the new token and paste it into your `.env` file as `DISCORD_TOKEN`.
5. Under `Privileged Gateway Intents`, enable `Message Content Intent`.
6. Click on `Installation` in the left sidebar, then check `User Install` and uncheck `Guild Install`.
7. Under `Install Link`, select `Discord Provided Link`. Then copy the link section and paste it into your browser and click `Authorize`.
Once you start the Discord bot, it should be usable in any server or the bot's DMs! Run `/ping` to test if it's working.

If you used the old method where you had to invite the bot to a server, then you can start at step 6. Then once you confirm the bot is working with slash commands (`/ping`), you can remove the old bot from your server.
