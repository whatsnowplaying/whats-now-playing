KickBot
=======

**What's Now Playing** integrates with Kick.com to provide chat bot functionality with track announcements.

Kick Chat Support
------------------

The current Kick integration supports:

* **Track Announcements**: Automatic announcements when tracks change
* **Template-based Messages**: Rich formatting with metadata variables
* **Smart Message Splitting**: Intelligent splitting of long messages

**Coming Soon**:

  * Interactive chat commands and user input processing.
  * Point Redemptions

Authentication
--------------

To use Kick.com integration, you'll need to set up OAuth2 authentication with your Kick account.


.. image:: images/kickbot-developer-screen.png
   :target: images/kickbot-developer-screen.png
   :alt: Kick.com Developer tab in settings

#. Go to your Kick streamer settings and navigate to the **Developer** tab to create an application.
#. Create a new OAuth2 application with these important settings:

   * **Application Type**: Set to **Bot** (required for chat functionality)
   * **Application Name**: This will be the name displayed in chat when the bot sends messages
   * Note down your Client ID and Client Secret
   * Set Redirect URI to ``http://localhost:8899/kickredirect`` (port must match your webserver settings, default is 8899)

.. image:: images/kickbot-edit-app-screen.png
   :target: images/kickbot-edit-app-screen.png
   :alt: Kick.com Edit App Screen

#. Click on the Edit button to make a few more changes
#. Scopes Requested should include the following for current and future features:

   * Read user information (including email address) - ``user:read``
   * Write to chat feed - ``chat:write``
   * Subscribe to events (read chat feed, follows, subscribes, gifts) - ``events:subscribe``

#. You should also make sure to select the option to make it a bot account.


.. image:: images/kickbot-account-settings.png
   :target: images/kickbot-account-settings.png
   :alt: What's Now Playing Kick settings

#. In **What's Now Playing** settings:

   * Enter your Client ID and Client Secret
   * Set your Kick channel name
   * Click "Authenticate with Kick" to complete OAuth2 setup

Template Features
-----------------

Kick templates support powerful formatting features:

* **Template Variables**: All standard metadata variables (``{{ artist }}``, ``{{ title }}``, etc.)
* **Message Splitting**: Use ``{{ startnewmessage }}`` to split long announcements across multiple messages
* **Smart Splitting**: Messages longer than 500 characters are automatically split at sentence or word boundaries using NLTK

Example announcement template::

    {% if artist %}{{ artist }} - {% endif %}"{{ title }}"
    {% if album %} from {{ album }}{% endif %}
    {{ startnewmessage }}
    {% if artistshortbio %}{{ artistshortbio }}{% endif %}

Configuration
-------------

#. Enable Kick chat in the Kick settings tab
#. Configure your OAuth2 credentials
#. Set up your announcement template
#. Configure announcement delay if needed
#. Test the connection with the "Authenticate with Kick" button

Current Limitations
-------------------

* **Chat Commands**: Interactive commands are not yet implemented (coming soon)
* **Permissions**: User permission system will be added with command support

The Kick integration uses the same intelligent message splitting technology as the enhanced Twitch integration, ensuring that long messages with rich metadata are delivered in full while respecting platform limits.