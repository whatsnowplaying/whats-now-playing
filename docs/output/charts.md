# Charts

Charts sends track metadata to the What's Now Playing Charts service for tracking and analytics.

## What it provides

The Charts output automatically submits your track information to the What's Now Playing Charts service,
allowing you to:

* Track your most played songs and artists
* View listening statistics and trends
* Participate in community charts
* Share your music data with the What's Now Playing ecosystem

## Getting your Secret Key

Before setting up Charts output, you'll need to get your authentication key:

1. Visit [whatsnowplaying.com](https://whatsnowplaying.com)
2. Click **Login with Twitch** or **Login with Kick**
3. Complete the OAuth login process
4. Go to your **Dashboard**
5. Click **Regenerate API Key** to reveal your key (required for first-time users)
6. Copy your **API Key** and save it securely

## Setup

To enable Charts output:

1. Navigate to **Settings** → **Output Destinations** → **Charts**
2. Check the **Enable** checkbox
3. Enter your **Secret Key** from the dashboard above
4. Click **Save**

## Configuration

* **Enable** - Turn Charts output on or off
* **Secret** - Your authentication key for the Charts service (required)

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
