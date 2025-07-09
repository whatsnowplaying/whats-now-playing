# Remote Services

A common streaming configuration is to have more than one computer
involved, such as one computer working as the DJ machine and one computer
for processing the stream.  In some very advanced configurations, there
might even be more than on DJ on different computers swapping back and
forth!

**What's Now Playing** supports a configuration where each setup has
their own app configuration running.  One or more installations on
DJ computers send the track information to a central one.  That
central one will then perform any additional lookups and send the
output to anything configured such as Twitch.

## Settings

* Server Side

1. You will need to enable the web server
2. Also in webserver, you may optionally set a Secret that is required to be set on any
   other **What's Now Playing** installation that talks to it
3. Set the Input to be 'Remote'
4. It is recommended to enable Artist Extras on the Server

* Client Side

1. Go to 'Remote Output'
2. Enable it
3. Set the Server to be either the hostname or IP address of the computer
   acting as the server
4. Set the port to be the server's webserver port
5. If the Server has a Secret set, you will need to set that as well

> NOTE: Some content, such as cover art, will not be sent to the remote server.

## Other Settings

It should be noted that there is no protection against multiple Twitch chat bots,
multiple Kick bots, etc.  This can result in double posts and other weirdness.
On the client computers, you will want to turn off such services.  Here is a
non-complete list of things to check:

* Artist Extras
* Discord
* Kick Chat
* Twitch (Chat and Requests)

Note that Recognition services such as AcoustID support are required to run
on the client computer as they need access to the local file for those systems
that provide access to it.
