# Discord

**What's Now Playing** supports two Discord modes, which can run simultaneously:

* **Bot Mode**: A bot account joins your Discord server, updates its presence with the
  currently playing track, and can optionally post track announcements to a channel.
* **Rich Presence Mode**: Updates your own Discord user's Rich Presence status via the
  Discord desktop app running on the same machine.

## What's Now Playing Configuration

[![Discord settings in What's Now Playing](images/wnp_discord_settings.png)](images/wnp_discord_settings.png)

1. Open Settings from the **What's Now Playing** icon
2. Select **Discord** from the **Streaming & Chat** section
3. Check **Enable Bot Mode** and/or **Enable Rich Presence** depending on which modes you want
4. Fill in the fields for each enabled mode (see setup sections below)
5. Set the **Presence Template** for the status text shown in Bot Mode presence and Rich Presence.
   Click **Preview** next to the field to see rendered output using sample metadata, and
   **Use This Template** to apply a template from the dropdown
6. Click **Save**

## Bot Mode Setup

Bot Mode connects a bot account to your Discord server and updates its presence with the
currently playing track. If Twitch is also configured and enabled, the presence will show
as a Twitch stream link.

### Step 1: Go to the Discord Developer Portal

Go to <https://discord.com/developers/applications>. If this is your first time, you may
see a "What brings you to the Developer Portal?" onboarding screen.

[![Discord developer portal onboarding](images/discord-onboarding.png)](images/discord-onboarding.png)

Select **Build a Bot** and click **Continue to Portal**.

### Step 2: Create a New Application

Click **New Application** in the upper right corner.

[![Create a new app dialog](images/discord-createnewapp-dialog.png)](images/discord-createnewapp-dialog.png)

Give your application a name (e.g., `wnpbot`), agree to the Developer Terms of Service,
and click **Create**. You may be asked to complete a CAPTCHA.

### Step 3: Note Your Application ID

You will land on the **General Information** page.

[![Discord app general information](images/discord-appconfig.png)](images/discord-appconfig.png)

Copy the **Application ID**. You will need this for Rich Presence Mode. For Bot Mode only,
you can skip this for now.

### Step 4: Get a Bot Token

In the left sidebar, click **Bot**.

[![Discord app sidebar showing Bot option](images/discord-botsidebar.png)](images/discord-botsidebar.png)

[![Discord bot options](images/discord-botopts1.png)](images/discord-botopts1.png)

Click **Reset Token**. Discord will ask you to log in again to confirm. After authenticating,
the token will be displayed once. Copy it immediately, as you cannot view it again without
regenerating it. No privileged intents are required for **What's Now Playing**.

### Step 5: Invite the Bot to Your Server

In the left sidebar, click **Installation**.

[![Discord installation page](images/discord-invite.png)](images/discord-invite.png)

Under **Installation Contexts**, make sure only **Guild Install** is checked (not User Install).

Under **Default Install Settings → Guild Install**, set the **Scopes** to include `bot`
and set the following **Permissions**:

* View Channels
* Send Messages
* Embed Links
* Attach Files
* Read Message History

Copy the **Discord Provided Link** and open it in a browser.

[![Discord add app dialog](images/discord-postinvitelink.png)](images/discord-postinvitelink.png)

Click **Add to Server**.

[![Discord add to server authorization](images/discord-addtoserver.png)](images/discord-addtoserver.png)

Select your server from the dropdown and click **Authorize**. You must have **Manage
Server** permission in the server to add a bot.

### Step 6: Configure What's Now Playing

Paste the bot token into the **Bot Token** field in **What's Now Playing**'s Discord
settings. Click **Save** and restart. The bot will appear in your server and begin
updating its presence as tracks change.

> **Note**: Discord enforces a rate limit on presence updates. **What's Now Playing**
> waits at least 20 seconds between updates to stay within this limit, so there may be
> a short delay before the bot's status reflects a new track. This is expected behavior.

## Channel Posting

Bot Mode can post a track announcement to a Discord text channel each time a new track plays.

### Setup

1. Right-click the channel in Discord and select **Copy Channel ID** (Developer Mode must be
   enabled in Discord's Advanced settings)
2. Paste the ID into the **Channel ID** field in **What's Now Playing**'s Discord settings
3. Optionally set a **Channel Template** for the message format. If left empty, the
   Presence Template is used. Click **Preview** to open a preview of the rendered output
   using sample metadata, and **Use This Template** to apply a template from the dropdown
4. To include cover art with each post, check **Attach cover image to channel posts** and
   set the **Max size (px)** for the image. The default is 200 px, which keeps file sizes
   small. The maximum is 500 px.
5. Click **Save**

The bot must have **Send Messages** and **Attach Files** permissions in the target channel.

## Rich Presence Mode Setup

Rich Presence Mode updates your own Discord status using the Discord desktop app running
locally on the same machine. The Discord app must be running for Rich Presence to connect.
If Discord is not running when **What's Now Playing** starts, it will retry the connection
automatically every 20 seconds.

### Step 1: Create an Application and Get a Client ID

Follow Steps 1–3 from Bot Mode above to create an application. The **Application ID**
shown on the General Information page is your Client ID.

### Step 2: Configure What's Now Playing

Paste the Application ID into the **Client ID** field in **What's Now Playing**'s Discord
settings. No bot token, no server invite, and no privileged intents are needed for Rich
Presence Mode.

Click **Save** and restart **What's Now Playing**.

> **Note**: Discord only allows one application to display Rich Presence at a time. If
> you are playing a game or running another app that also updates Rich Presence,
> **What's Now Playing** may be suppressed until the other application stops. Close
> any competing applications if Rich Presence is not appearing.
>
> **Note**: Discord enforces a rate limit on presence updates. **What's Now Playing**
> waits at least 20 seconds between updates to stay within this limit, so there may be
> a short delay before your status reflects a new track. This is expected behavior.
