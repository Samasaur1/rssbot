# RssBot

RssBot is a Discord bot that watches RSS feeds, and posts new entries in those feeds to Discord channels. Once added to a server, users can run `@RssBot add https://samasaur1.github.io/feed.xml`, <kbd>@RssBot list</kbd> and <kbd>@RssBot remove https://samasaur1.github.io/feed.xml</kbd> to control which feeds are being watched in which channels.

It requires Python 3 (I'm using Python 3.9, although I'm not sure if the minor version matters all that much), discord.py, feedparser, and validators. You can install the dependencies by running `pip install -r requirements.txt`, though I recommend doing so in a virtualenv.

RssBot is a descendant of [oobot](https://github.com/InternetUnexplorer/oobot).
