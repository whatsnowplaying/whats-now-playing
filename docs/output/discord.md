# Discord

**What's Now Playing**'s support of Discord is very preliminary at the
moment. It supports two modes of operation, both of which may be done
simultaneously:

Bot Mode: Using a token, update the presence of a bot account that
includes a link to your stream if Twitch is also configured.

Client Mode: If the Discord app is running and a Client ID is provided,
update the Discord user's status to the playing song.

## Configuration

[![Discord settings in What's Now Playing](images/wnp_discord_settings.png)](images/wnp_discord_settings.png)

### Generic Settings

1. In order to even start with Discord mode, it must be enabled
2. The template selected here is what will be used to fill in the
   status text.

### Client Mode

1. If the Discord app is not running, start it first.
2. Go to your [Discord Developers](https://discord.com/developers/) page
3. Create an application
4. After naming, take the Client ID and put into **What's Now Playing**'s Discord page.
5. Restart **What's Now Playing**. Subsequent launches will connect to Discord as long as the Discord app is already running.

### Bot Mode

1. Go to your [Discord Developers](https://discord.com/developers/) page
2. Create an application
3. Build-a-bot
4. Make a note of the token from the bot page
5. Invite your bot to your Discord channel
6. Put that token into the Discord settings
7. Restart **What's Now Playing**. Subsequent launches will connect to
   Discord as long as the Discord app is already running.
