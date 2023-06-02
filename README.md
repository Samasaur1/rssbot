# RssBot

RssBot is a Discord bot that watches RSS feeds, and posts new entries in those
feeds to Discord channels. Once added to a server, users can run `@RssBot add
https://samasaur1.github.io/feed.xml`, `@RssBot list` and `@RssBot remove
https://samasaur1.github.io/feed.xml` to control which feeds are being watched
in which channels.

RssBot requires discord.py, feedparser, and validators. If you have a version
of [Nix](https://nixos.org) that supports flakes, you can build RssBot with
`nix build` and run it with `nix run`.

RssBot is a descendant of [oobot](https://github.com/InternetUnexplorer/oobot).
