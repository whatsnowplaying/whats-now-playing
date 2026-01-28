# Guess Game

**What's Now Playing** includes an interactive hangman-style game that runs in your Twitch chat, allowing
viewers to guess the currently playing track and artist. Players earn points for correct guesses, with a
leaderboard system to track top performers across your stream session and all-time.

## What It Provides

* **Interactive Chat Game**: Viewers type commands like `!guess e` or `!guess house` to play
* **Real-time OBS Display**: Shows masked track/artist names and game state in your stream overlay
* **Leaderboard System**: Tracks both session and all-time scores with configurable size
* **Flexible Solve Modes**: Configure whether viewers must guess track, artist, or both
* **Smart Scoring**: Points awarded based on letter frequency (rare letters = more points)
* **Automatic Games**: New games start when your track changes and end after a configurable duration
* **User Statistics**: Players can check their stats with a customizable command (default: `!mystats`)

## Setup

### Prerequisites

Before enabling the Guess Game, you must have:

1. **Twitch Bot configured**: See [TwitchBot](twitchbot.md) for authentication setup
2. **Webserver enabled**: See [Webserver](webserver.md) for configuration

### Enabling the Guess Game

**macOS:**

1. Click the **What's Now Playing** menu bar icon
2. Check **Enable Guess Game**

**Windows:**

1. Right-click the **What's Now Playing** system tray icon
2. Check **Enable Guess Game**

**Linux:**

1. Click the **What's Now Playing** system tray icon
2. Check **Enable Guess Game**

### Configuration

1. Open Settings from the **What's Now Playing** menu/tray icon
2. Select **Guess Game** from the list of settings available
3. Configure the settings on each tab:

#### Basic Settings Tab

[![Guess Game Basic Settings](images/guessgame_basic.png)](images/guessgame_basic.png)

| Setting | Description | Default |
|---------|-------------|---------|
| Guess Command | Chat command viewers use to submit guesses | `guess` |
| Stats Command | Chat command viewers use to check their statistics | `mystats` |
| Game Duration | Maximum time in seconds before game times out | `180` (3 minutes) |
| Leaderboard Size | Number of top players shown on leaderboard | `10` |
| First Solver Bonus Threshold | Difficulty threshold (0.0-1.0) for awarding first solver bonus | `0.70` |
| Solve Mode | How the game determines completion (see below) | Separate Solves |

**Solve Modes:**

* **Separate Solves**: Track and artist are independent objectives (players can solve one without the other)
* **Either**: Exact match of track OR artist wins the entire game
* **Both Required**: Players must guess both track AND artist together to win

#### Advanced Tab

[![Guess Game Advanced Settings](images/guessgame_advanced.png)](images/guessgame_advanced.png)

**Scoring Configuration:**

| Setting | Description | Default |
|---------|-------------|---------|
| Common Letter Points | Points for guessing common letters (e, a, o, etc.) | `1` |
| Uncommon Letter Points | Points for guessing uncommon letters (d, h, etc.) | `2` |
| Rare Letter Points | Points for guessing rare letters (x, z, q, etc.) | `3` |
| Correct Word Points | Points for guessing a correct word in track/artist | `10` |
| Wrong Word Points | Penalty for guessing an incorrect word | `-1` |
| Complete Solve Points | Bonus for completely solving track or artist | `100` |
| First Solver Bonus | Additional bonus for being first to solve (on difficult tracks) | `50` |

**Advanced Options:**

| Setting | Description | Default |
|---------|-------------|---------|
| Auto Reveal Common Words | Automatically reveal very common words (the, and, of, etc.) | Disabled |
| Time Bonus Enabled | Award bonus points for solving quickly | Disabled |

**Leaderboard Management:**

* **Clear All Leaderboards** button: Permanently deletes all user scores (session and all-time)

## OBS Integration

The Guess Game provides two OBS browser sources for displaying game information on your stream:

### Game Display

Shows the current game state with masked track/artist names:

1. Add a **Browser** source in OBS
2. Set URL to: `http://localhost:8899/guessgame.htm`
3. Set dimensions: `1920x200` (or adjust to your layout)
4. Customize the display by editing `templates/guessgame.htm`

**Display Shows:**

* Masked track name (e.g., `h___e __ _he ___i__ s__`)
* Masked artist name (e.g., `_he __i__ls`)
* Time remaining in seconds
* Guessed letters list
* Game status (Active, Solved, Timeout, Waiting)

### Leaderboard Display

Shows top players for session or all-time:

1. Add a **Browser** source in OBS
2. Set URL to: `http://localhost:8899/guessgame-leaderboard.htm`
3. Set dimensions: `600x800` (or adjust to your layout)
4. Customize the display by editing `templates/guessgame-leaderboard.htm`

**Leaderboard Shows:**

* Rank
* Username
* Total score
* Number of correct guesses
* Configurable to show session or all-time stats

## How It Works

### Game Flow

1. **Track Changes**: When a new track starts playing, the Guess Game automatically begins
2. **Chat Commands**: Viewers type `!guess <letter or word>` in Twitch chat
3. **Guess Processing**:
    * **Single letters**: Revealed if present in track/artist, points awarded by frequency
    * **Words**: Checked against track/artist name, bonus points if correct
    * **Complete matches**: If track/artist fully matches, that objective is solved
4. **Game Ends**: When solved or time expires, game ends and scores are saved
5. **Next Track**: Process repeats for the next song

### Guess Normalization

The game intelligently handles variations in guesses:

* **Case insensitive**: `HOUSE`, `house`, and `House` are all equivalent
* **Ampersand variants**: `&`, `and`, and `n` are treated as interchangeable
* **Punctuation**: Periods in artist names (e.g., `N.W.A` vs `NWA`) are handled

### Scoring System

Points are awarded based on guess type and letter frequency:

* **Common letters** (e, a, o, i, n, t, s, r, h, l): 1 point each
* **Uncommon letters** (d, c, u, m, p, f, g, w, y, b): 2 points each
* **Rare letters** (v, k, x, j, q, z): 3 points each
* **Correct words**: 10 points
* **Wrong words**: -1 point (penalty)
* **Complete solve**: 100 point bonus
* **First solver bonus**: 50 additional points (on difficult tracks with threshold above configured value)

### Difficulty Calculation

The game calculates difficulty based on:

* Total number of unique letters in track and artist
* Length of track and artist names
* Tracks with difficulty above the configured threshold award first solver bonus

## Templates

The Guess Game uses Jinja2 templates for chat responses and OBS display:

### Chat Templates

**twitchbot_guess.txt**: Response when a viewer makes a guess

```jinja2
@{{ cmduser }}: {% if guess_already_guessed %}Already guessed!
{% elif guess_correct %}Correct! +{{ guess_points }} points.
{% else %}Wrong guess. {{ guess_points }} points.
{% endif %} Track: {{ masked_track }} | Artist: {{ masked_artist }} |
Time: {{ time_remaining }}s{% if game_solved %} | SOLVED!{% endif %}
```

**twitchbot_mystats.txt**: Response when a viewer checks their stats

```jinja2
@{{ cmduser }}: Session: {{ session_score }} points, {{ session_guesses }} guesses |
All-Time: {{ all_time_score }} points, {{ all_time_guesses }} guesses, {{ all_time_solves }} solves
```

### Template Variables

The Guess Game adds these variables for templating:

| Variable | Description |
|----------|-------------|
| `masked_track` | Track name with unguessed letters as underscores |
| `masked_artist` | Artist name with unguessed letters as underscores |
| `time_remaining` | Seconds remaining in current game |
| `guessed_letters` | List of letters already guessed |
| `game_status` | Current game state: `active`, `solved`, `timeout`, or `waiting` |
| `game_solved` | Boolean: true if game is completely solved |
| `guess_correct` | Boolean: true if last guess was correct |
| `guess_points` | Points awarded/deducted for last guess |
| `guess_already_guessed` | Boolean: true if letter/word was already guessed |
| `session_score` | User's score for current stream session |
| `session_guesses` | User's guess count for current stream session |
| `all_time_score` | User's all-time score |
| `all_time_guesses` | User's all-time guess count |
| `all_time_solves` | User's all-time solve count |

## Troubleshooting

### Game Not Starting

* Verify Twitch bot is connected (test with `!whatsnowplayingversion`)
* Check that Guess Game is enabled in the menu/tray icon
* Ensure a track is actually playing (game starts on track changes)

### Chat Commands Not Working

* Confirm chat permissions are set in Twitch settings
* Check that template files exist: `twitchbot_guess.txt` and `twitchbot_mystats.txt`
* Verify bot has proper OAuth authentication

### OBS Display Not Updating

* Confirm webserver is enabled and running on correct port
* Check browser source URL matches your webserver port
* Try refreshing the browser source in OBS

### Scores Not Saving

* Check logs for database errors
* Verify write permissions in **What's Now Playing** cache directory
* Try clearing leaderboards and restarting

## Tips for Stream Engagement

* **Announce the game**: Create a chat command explaining how to play
* **Show the leaderboard**: Display top players between songs
* **Adjust difficulty**: Shorter timeouts and harder solve modes increase challenge
* **Create incentives**: Reward top leaderboard players with channel points or other prizes
* **Test first**: Try the game offline to ensure everything works before going live
