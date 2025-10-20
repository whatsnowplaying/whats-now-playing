# Charts

Charts sends track metadata to the What's Now Playing Charts service for tracking and analytics.

## What it provides

The Charts output automatically submits your track information to the What's Now Playing Charts service,
allowing you to:

* Track your most played songs and artists
* View listening statistics and trends
* Participate in community charts
* Share your music data with the What's Now Playing ecosystem

## Automatic Setup

Charts is **enabled by default** and requires no manual configuration. What's Now Playing automatically:

* Generates an anonymous API key during first startup
* Begins tracking your music immediately
* Stores your key securely for future sessions

## Claiming Your Anonymous Key

To access advanced features and view your data online:

1. Navigate to **Settings** → **Output Destinations** → **Charts**
2. Copy your auto-generated **Secret Key** from the input field
3. Visit [whatsnowplaying.com/signup](https://whatsnowplaying.com/signup) to create an account
4. Sign up using **Twitch** or **Kick** credentials
5. Once logged in, enter your copied key to claim it and link it to your account

## Configuration

* **Enable** - Turn Charts output on or off (enabled by default)
* **Secret** - Your auto-generated anonymous API key (automatically created)

## How it works

When enabled, the Charts plugin:

* Automatically sends track metadata when songs change
* Queues submissions when the service is temporarily unavailable
* Retries failed submissions automatically
* Excludes sensitive information (filenames, system data, etc.)
* Only sends essential track data (artist, title, album, etc.)

## Queue System

The Charts plugin includes a robust offline queue system:

* **Automatic queuing** - Track updates are queued if the Charts service is down
* **Persistent storage** - Queued items survive application restarts
* **Automatic retry** - Failed submissions are retried when the service comes back online
* **Secure storage** - Authentication keys are never stored in queue files

## Troubleshooting

* **Authentication failed** - Verify your secret key is correct
* **Connection errors** - Check your internet connection
* **Invalid request data** - Ensure you're using a supported What's Now Playing version

The Charts service processes standard track metadata including artist, title, album, genre, and timing information.
Personal data like file paths and system information are automatically excluded from submissions.
