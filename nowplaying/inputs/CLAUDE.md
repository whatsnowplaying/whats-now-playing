# Input Plugin Documentation

Input plugins read what is playing from DJ software. `__init__.py` holds the base
class and the lifecycle contract; everything else here is one plugin, or a thin
wrapper around a package that is (`denon.py`, `rekordbox.py`, `serato.py`).

## The lifecycle contract

Two things drive a plugin independently and neither knows about the other:

* `processes/trackpoll.py` in the running app
* `wizard/verify.py`, which constructs the plugin itself and never touches
  trackpoll

That is why the rules below are rules rather than conventions. Before they were
written down, each caller had grown its own defences against the same unknowns
and guessed differently.

1. `start()` returns promptly, or says in its own docstring that it does not.
   Denon runs discovery and Icecast waits on a broadcaster; callers bound those
   with a timeout
2. `start()` is atomic: it either succeeds or leaves nothing allocated
3. `stop()` is safe at any time, including after a failed or never-called
   `start()`. Callers run it on every path out, so check what is held rather
   than assuming. It has no deadline of its own, so trackpoll bounds every call
   through `_stop_plugin()`
4. Recoverable conditions are the plugin's to retry, silently. No raising, no
   caller-side loop
5. `start()` does not raise for anything operational. A busy port, an
   unreachable host or a key that does not work are reported through `status()`.
   Exceptions are for bugs

## status()

An exception can only say "dead". The caller needs to know what to *do*, and
only the plugin knows, so `status()` returns an `InputStatus`. Build it with one
of the named constructors rather than by hand:

| constructor | meaning | caller |
| --- | --- | --- |
| `InputStatus()` | working | poll |
| `InputStatus.starting(msg)` | not ready yet | poll; this is what licenses the setup |
| `InputStatus.waiting(msg)` | recoverable, being retried here | poll, quietly |
| `InputStatus.needs_user(msg)` | configuration is wrong | stop polling, show the message |
| `InputStatus.needs_restart(msg)` | a `stop()`/`start()` would clear it | rebuild after 30s |
| `InputStatus.broken(msg)` | unrecoverable | stop polling, show the message |

Each takes an optional second `detail` for the log. `OK` is the only case with
no message, which is why it is the only one spelled as a bare constructor: the
message is shown to a person and the caller cannot invent one. Its absence is
how `verify.py` ended up scraping exception text to find something to display,
so the signatures require it now.

`InputStatus` is truthy for the first three, so `if not plugin.status():` reads
as "not worth polling". Note that is broader than "setup finished" -- `WAITING`
is truthy -- so a guard meaning the latter tests `health is InputHealth.OK`.

### status() is called every cycle

Including while the caller has stopped polling. That is not incidental, it is
the recovery mechanism: a plugin in `NEEDS_USER` re-reads the setting that was
wrong and reports `STARTING` once it looks right.

So `status()` may read configuration -- Icecast has always re-read its port this
way -- but must not open a socket, a database or a file. Anything like that
happens on the plugin's own schedule, and `status()` hands back the answer.

### Report STARTING, not OK

The mistake to avoid, made four times during the original conversion: noticing
the setting has been fixed and reporting `OK`. `start()` has usually given up by
then and built nothing, so `getplayingtrack()` returns `None` off its own guard
and the plugin looks healthy while doing nothing.

`STARTING` is what tells the caller to poll, and `getplayingtrack()` is where
the reopen belongs -- that call is already allowed to do work. `rekordbox.py`
does this for its key, `jriver.py` for its session, `mpris2.py` for its handler.

### Transient means WAITING, not NEEDS_USER

Nothing rebuilds a plugin on `NEEDS_USER`, so it is only for something a person
has to change. An absent database file or an unreachable host is `WAITING`: the
drive may be mounted, the other machine may come back, and the settings may be
perfectly correct meanwhile.

## Watchers

Most plugins here watch files. Two traps:

* **`observer.is_alive()` is the wrong question.** That is watchdog's event
  dispatcher, which loops on `dispatch_events()` and stays up whether or not any
  emitter still feeds it. The emitters run on their own threads and are what
  dies -- scheduling a path another observer already holds kills one, silently,
  after `start()` returned. Check `observer.emitters` individually;
  `db.DBWatcher.is_alive()` does this
* **`schedule()` raises on a missing directory** under `PollingObserver` and
  inotify, but not under macOS fsevents. Check the path exists first, or a Mac
  will pass and everything else will not

## EarShot is not like the others

`earshot.Plugin` subclasses `remote.Plugin`, and
`trackpoll._manage_earshot_plugin()` runs it alongside *any* source that is not
earshot or remote, because it can always accept input. Consequences:

* remote's watcher is live whenever EarShot is enabled, whatever input is
  selected, so two observers can want the same file
* trackpoll keeps calling `gettrack()` even when the chosen source is unusable,
  because that is the only caller of `_check_earshot_override()`
* its `status()` is read too, on its own restart clock, since it inherits the
  watcher above and is the plugin most likely to lose it

## Detection

`detect()` returns `Detected(present, settings, fallback)` and writes nothing.
`settings` is what the plugin *would* configure; callers decide, because the
policy differs between first run, Redetect, and the wizard showing a found path
next to a configured one. Present with empty `settings` is normal: Serato 4
derives its path on demand, and Rekordbox needs a key that cannot be detected.

`fallback=True` marks presence that comes from a platform capability rather than
from finding the user's software -- MPRIS2 wherever D-Bus works, WinMedia
wherever the winrt bindings import -- so it never outranks real DJ software.
