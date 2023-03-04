from datetime import datetime, timezone, timedelta
import hashlib
from asyncio import sleep, create_task
from os import environ
from random import randrange
from typing import List, Optional, Dict

import feedparser
import validators
from discord import Client, Intents, Message, Status, ActivityType, Activity, DMChannel, GroupChannel

RSS_FETCH_INTERVAL = 5 * 60 # 5 minutes

def verbose(*args) -> None:
    """Print the specified args only if $VERBOSE is set."""

    if "VERBOSE" in environ.keys():
        print("verbose:", *args)


class Entry:
    def __init__(self, entry):
        self.id = entry.get("id", None)
        self.link = entry.get("link", None)
        self.title = entry.get("title", None)
        self.summary_hash = hashlib.md5(entry["summary"].encode()).hexdigest() if "summary" in entry else None
        self.content_hash = hashlib.md5(entry["content"][0].value.encode()).hexdigest() if "content" in entry else None

    def __eq__(self, other):
        verbose("in __eq__")
        if not other:
            return False
        if self.id and other.id:
            verbose(f"match by id: {self.id == other.id}")
            return self.id == other.id
        if self.link and other.link:
            verbose(f"match by link: {self.link == other.link}")
            return self.link == other.link
        if self.title and other.title:
            verbose(f"match by title: {self.title == other.title}")
            return self.title == other.title
        if self.summary_hash and other.summary_hash:
            verbose(f"match by s_h: {self.summary_hash == other.summary_hash}")
            return self.summary_hash == other.summary_hash
        verbose(f"match by c_h: {self.content_hash == other.content_hash}")
        return self.content_hash == other.content_hash

    def output(self):
        if self.title and self.link:
            return f"{self.title} ({self.link})"
        elif self.link:
            return self.link
        return "a post"


class FeedData:
    def __init__(self, url: str):
        self.url: str = url
        self.etag: Optional[str] = None
        self.modified: Optional[str] = None
        self.previous_entry: Optional[Entry] = None #The most recent "nwewst entry" — e.g., entries[0] from the last time we fetched the feed

    def new_entries(self):
        verbose("in new_entries")
        if self.previous_entry:
            verbose(f"previous entry {self.previous_entry.title}")
        else:
            verbose("no prev entry")
        if self.etag or self.modified:
            verbose("etag/modified")
            d = feedparser.parse(self.url, etag=self.etag, modified=self.modified)
            # if self.etag:
            #     d = feedparser.parse(self.url, etag=self.etag)
            # else:
            #     d = feedparser.parse(self.url, modified=self.modified)
            if d.status == 304:
                verbose("status 304")
                return []
        else:
            verbose("parsing normally")
            d = feedparser.parse(self.url)

        verbose("d has been parsed")
        if "etag" in d:
            if d.etag != self.etag:
                verbose("new etag")
                self.etag = d.etag
        if "modified" in d:
            if d.modified != self.modified:
                verbose("new modified")
                self.modified = d.modified

        new_entries = []
        for _entry in d.entries:
            verbose(f"entry {_entry.get('title', _entry.get('link', '???'))}")
            entry = Entry(_entry)
            verbose(f"entry class {entry}")
            if entry == self.previous_entry:
                verbose("equal")
                break
            verbose("adding to list")
            new_entries.append(entry)

        if len(new_entries) == 0:
            return []

        self.previous_entry = new_entries[0]
        verbose(self.previous_entry)
        return new_entries


async def say(message: Message, msg: str, maxrange: int = 3) -> None:
    if maxrange < 1:
        sleep_time = 0
    elif maxrange == 1:
        sleep_time = 1
    else:
        sleep_time = randrange(1, maxrange)
    async with message.channel.typing():
        await sleep(sleep_time)
        await message.reply(msg)


class RssBot(Client):
    def __init__(self, channel_id: int, feeds: List[str], **options) -> None:
        super().__init__(intents=Intents(guilds=True, messages=True), **options)
        self.feeds = {feed: [channel_id] for feed in feeds}
        self.feed_data: Dict[str, FeedData] = {feed: FeedData(feed) for feed in feeds}
        self.task = None

    async def update_status(self) -> None:
        feed_count = len(self.feeds)
        stat = Status.idle if feed_count == 0 else Status.online
        fstr = "1 feed" if feed_count == 1 else f"{feed_count} feeds"
        await self.change_presence(status=stat, activity=Activity(name=fstr, type=ActivityType.watching))

        self.schedule_updates()

    async def on_ready(self) -> None:
        """Called when the bot is ready to start."""

        print(f"Logged in as {self.user}!")

        await self.update_status()

        await self.get_channel(1080991601502986331).send("Now running")

    async def on_message(self, message: Message) -> None:
        """Called when a message is sent."""

        # Never respond to our own messages.
        if message.author == self.user:
            return

        if isinstance(message.channel, DMChannel):
            def log(s: str):
                print(f"[{datetime.now(timezone.utc).isoformat()}] {s} in DM with {message.author} ({message.channel.id})")
        elif isinstance(message.channel, GroupChannel):
            def log(s: str):
                print(f"[{datetime.now(timezone.utc).isoformat()}] {s} in group DM {f'{message.channel.name} ({message.channel.id})' if message.channel.name else message.channel.id} from {message.author}")
        else:
            def log(s: str):
                print(f"[{datetime.now(timezone.utc).isoformat()}] {s} to #{message.channel.name} ({message.channel.id}) from {message.author}")

        # if message.author.id != 377776843425841153:
        #     print(f"Request from {message.author} ({message.author.id})")
        #     await say(message, "Unauthorized user")
        #     return

        if self.user.mentioned_in(message):
            msg = message.content.split(">", maxsplit=1)[1].strip(" ")
            _msg = msg.split(" ", maxsplit=1)
            cmd = _msg[0]
            if cmd == "add":
                url = _msg[1]
                log(f"Request to add '{url}'")
                if url in self.feeds:
                    if message.channel.id in self.feeds[url]:
                        await say(message, f"Already watching {url} in this channel")
                    else:
                        self.feeds[url].append(message.channel.id)
                        await say(message, f"Now watching {url} in this channel")
                else:
                    if validators.url(url):
                        self.feeds[url] = [message.channel.id]
                        await self.update_status()
                        await say(message, f"Now watching {url} in this channel")
                    else:
                        await say(message, f"Not a valid URL")
            elif cmd == "remove":
                url = _msg[1]
                log(f"Request to remove '{url}'")
                if url in self.feeds and message.channel.id in self.feeds[url]:
                    self.feeds[url].remove(message.channel.id)
                    print("Found")
                    if len(self.feeds[url]) == 0:
                        del self.feeds[url]
                        print("Was last url for feed, so feed is removed")
                        await self.update_status()
                    await say(message, f"Removed {url} from the feeds for this channel")
                else:
                    await say(message, f"Could not find {url} in the feeds for this channel")
                    print("Not found")
            elif cmd == "list":
                log(f"Request to list feeds")
                feeds_in_channel = []
                for feed in self.feeds:
                    if message.channel.id in self.feeds[feed]:
                        feeds_in_channel.append(feed)
                if len(feeds_in_channel) == 0:
                    await say(message, "No feeds in this channel")
                    return
                fstr = "\n".join(feeds_in_channel)
                await say(message, f"""
**Feeds in this channel**:
{fstr}
""", 5)
            elif cmd == "help":
                log(f"Request for help")
                await say(message, """
To add a feed, try "<@1080989856248893521> add https://samasaur1.github.io/feed.xml"
To remove a feed, try "<@1080989856248893521> remove https://samasaur1.github.io/feed.xml"
To list all feeds in this channel, try "<@1080989856248893521> list"
""", 5)
            elif cmd == "status":
                log(f"Request for status")
                if message.author.id != 377776843425841153:
                    await say(message, "Unauthorized user")
                    # return
                td = datetime.now(timezone.utc) - self.last_check
                s = f"""
**Status:**
Time since last check: {td}
Estimated time until next check (approximate): {timedelta(seconds=RSS_FETCH_INTERVAL - td.total_seconds())}
Channels watching feed(s): {self.feeds.__repr__()}
"""
                await say(message, s, 1)
            elif cmd == "dump":
                log(f"Request to dump")
                if message.author.id != 377776843425841153:
                    await say(message, "Unauthorized user")
                    # return
                print("Unimplemented")
            else:
                log(f"Unknown command")
                await say(message, "Unknown command (try \"<@1080989856248893521> help\")")

    def schedule_updates(self) -> None:
        async def task():
            # await sleep(15)

            verbose("Checking feeds...")
            for feed in self.feeds:
                verbose(f"...{feed}")
                try:
                    if feed not in self.feed_data:
                        verbose("(first time checking; marking all posts as read)")
                        self.feed_data[feed] = FeedData(feed)
                        self.feed_data[feed].new_entries()
                        # Assume that newly-added blogs have had all their posts read already
                    entries = self.feed_data[feed].new_entries()
                    verbose(f"{len(entries)} entries")
                    if len(entries) == 0:
                        continue
                    for entry in entries:
                        print(f"New post on {feed}: {entry.output()}")

                    for channel_id in self.feeds[feed]:
                        channel = self.get_channel(channel_id)
                        async with channel.typing():
                            await sleep(randrange(1, 3))
                            for entry in entries:
                                await channel.send(f"New post from {feed}:\n{entry.output()}")
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise

            await sleep(RSS_FETCH_INTERVAL)
            # await sleep(45) #45 seconds

            self.schedule_updates()

            # While unlikely, it is possible that schedule_oob() could be called
            # while the current task is in the middle of running oob() (since
            # it has a small delay to simulate typing). Running oob() in a new
            # task should prevent this.
            # create_task(self.oob(channel, None))

            # Reset the delay to the maximum and start a new delay task.
            # Restarting the task ensures that the bot will eventually send an
            # oob again even if no one else sends one.
            # self.scheduled_oobs[channel_id]["delay_secs"] = self.DELAY_MAX
            # self.schedule_oob(channel_id)

        if self.task:
            verbose("Canceling task")
            self.task.cancel()

        delay_task = create_task(task(), name="rssbot.update")
        self.task = delay_task
        self.last_check = datetime.now(timezone.utc)


if __name__ == "__main__":
    token = environ["DISCORD_TOKEN"]
    print("loaded configuration from environment...")
    print("connecting to Discord...")
    # RssBot(1080991601502986331, ["https://samasaur1.github.io/feed.xml", "https://eclecticlight.co/category/updates/feed/atom/"]).run(token)
    RssBot(1080991601502986331, []).run(token)