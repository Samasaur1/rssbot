import hashlib
from asyncio import sleep, create_task
from os import environ
from random import randrange
from typing import List, Optional, Dict

import feedparser
from discord import Client, Intents, Message, Status, ActivityType, Activity


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
        print("in __eq__")
        if not other:
            return False
        if self.id and other.id:
            print(f"match by id: {self.id == other.id}")
            return self.id == other.id
        if self.link and other.link:
            print(f"match by link: {self.link == other.link}")
            return self.link == other.link
        if self.title and other.title:
            print(f"match by title: {self.title == other.title}")
            return self.title == other.title
        if self.summary_hash and other.summary_hash:
            print(f"match by s_h: {self.summary_hash == other.summary_hash}")
            return self.summary_hash == other.summary_hash
        print(f"match by c_h: {self.content_hash == other.content_hash}")
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
        print("in new_entries")
        if self.previous_entry:
            print(f"previous entry {self.previous_entry.title}")
        else:
            print("no prev entry")
        if self.etag or self.modified:
            print("etag/modified")
            d = feedparser.parse(self.url, etag=self.etag, modified=self.modified)
            # if self.etag:
            #     d = feedparser.parse(self.url, etag=self.etag)
            # else:
            #     d = feedparser.parse(self.url, modified=self.modified)
            if d.status == 304:
                print("status 304")
                return []
        else:
            print("parsing normally")
            d = feedparser.parse(self.url)

        print("d has been parsed")
        if "etag" in d:
            if d.etag != self.etag:
                print("new etag")
                self.etag = d.etag
        if "modified" in d:
            if d.modified != self.modified:
                print("new modified")
                self.modified = d.modified

        new_entries = []
        for _entry in d.entries:
            print(f"entry {_entry.get('title', _entry.get('link', '???'))}")
            entry = Entry(_entry)
            print(f"entry class {entry}")
            if entry == self.previous_entry:
                print("equal")
                break
            print("adding to list")
            new_entries.append(entry)

        if len(new_entries) == 0:
            return []

        self.previous_entry = new_entries[0]
        print(self.previous_entry)
        return new_entries


async def say(message: Message, msg: str, maxrange: int = 3) -> None:
    async with message.channel.typing():
        await sleep(randrange(1, maxrange))
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

        print(f"logged in as {self.user}!")

        await self.update_status()

        await self.get_channel(1080991601502986331).send("Now running")

    async def on_message(self, message: Message) -> None:
        """Called when a message is sent."""

        # Never respond to our own messages.
        if message.author == self.user:
            return

        if message.author.id != 377776843425841153:
            print(f"Request from {message.author} ({message.author.id})")
            await say(message, "Unauthorized user")
            return

        if self.user.mentioned_in(message):
            msg = message.content.split(">", maxsplit=1)[1].strip(" ")
            _msg = msg.split(" ", maxsplit=1)
            cmd = _msg[0]
            if cmd == "add":
                url = _msg[1]
                print(f"Request to add '{url}' to #{message.channel.name} ({message.channel.id}) from {message.author}")
                if url in self.feeds:
                    if message.channel.id in self.feeds[url]:
                        await say(message, f"Already watching {url} in this channel")
                    else:
                        self.feeds[url].append(message.channel.id)
                        await say(message, f"Now watching {url} in this channel")
                else:
                    #TODO: check if URL
                    if True:
                        self.feeds[url] = [message.channel.id]
                        await self.update_status()
                        await say(message, f"Now watching {url} in this channel")
                    else:
                        await say(message, f"Not a valid URL")
            elif cmd == "remove":
                url = _msg[1]
                print(f"Request to remove '{url}' from #{message.channel.name} ({message.channel.id}) from {message.author}")
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
                print(f"Request to list feeds in #{message.channel.name} ({message.channel.id}) from {message.author}")
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
                print(f"Request for help in #{message.channel.name} ({message.channel.id}) from {message.author}")
                await say(message, """
To add a feed, try "<@1080989856248893521> add https://samasaur1.github.io/feed.xml"
To remove a feed, try "<@1080989856248893521> remove https://samasaur1.github.io/feed.xml"
To list all feeds in this channel, try "<@1080989856248893521> list"
""", 5)
            else:
                print(f"Unknown command in #{message.channel.name} ({message.channel.id}) from {message.author}")
                await say(message, "Unknown command (try \"<@1080989856248893521> help\")")

    def schedule_updates(self) -> None:
        async def task():
            # await sleep(15)

            for feed in self.feeds:
                try:
                    if feed not in self.feed_data:
                        self.feed_data[feed] = FeedData(feed)
                        self.feed_data[feed].new_entries()
                        continue # Assume that newly-added blogs have had all their posts read already
                    entries = self.feed_data[feed].new_entries()
                    print(len(entries))
                    print([e.title for e in entries])

                    for channel_id in self.feeds[feed]:
                        channel = self.get_channel(channel_id)
                        async with channel.typing():
                            await sleep(randrange(1, 3))
                            for entry in entries:
                                await channel.send(f"New post from {feed}:\n{entry.output()}")
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise

            await sleep(5 * 60) #5 minutes
            # await sleep(45) #5 minutes

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
            print("Canceling task")
            self.task.cancel()

        delay_task = create_task(task(), name="rssbot.update")
        # delay_task = create_task(task(), name=f"oob_delay_fn.{channel_id}.{delay_secs}")
        self.task = delay_task
        # self.scheduled_oobs[channel_id]["delay_task"] = delay_task

#
#     def schedule_oob(self, channel_id: int) -> None:
#         """Schedule an oob to be sent in the future.
#
#         This will replace any existing scheduled oob for this channel. The delay
#         will be in the range of [0.5 * self.delay_secs, self.delay_secs)."""
#
#         channel = self.get_channel(channel_id)
#         channel_desc = f"#{channel.name} in {channel.guild.name}"
#
#         delay_task = self.scheduled_oobs[channel_id]["delay_task"]
#         delay_secs = self.scheduled_oobs[channel_id]["delay_secs"]
#
#         # If there is already an oob scheduled, cancel it.
#         if delay_task:
#             verbose(f"cancelling existing delay task '{delay_task.get_name()}'")
#             delay_task.cancel()
#
#         # Randomize the delay based on self.delay_secs.
#         delay_secs = max(self.DELAY_MIN, int(randrange(delay_secs // 2, delay_secs)))
#
#         # Create a task that waits delay seconds before calling oob().
#         async def task():
#             await sleep(delay_secs)
#
#             # While unlikely, it is possible that schedule_oob() could be called
#             # while the current task is in the middle of running oob() (since
#             # it has a small delay to simulate typing). Running oob() in a new
#             # task should prevent this.
#             create_task(self.oob(channel, None))
#
#             # Reset the delay to the maximum and start a new delay task.
#             # Restarting the task ensures that the bot will eventually send an
#             # oob again even if no one else sends one.
#             self.scheduled_oobs[channel_id]["delay_secs"] = self.DELAY_MAX
#             self.schedule_oob(channel_id)
#
#         delay_task = create_task(task(), name=f"oob_delay_fn.{channel_id}.{delay_secs}")
#         self.scheduled_oobs[channel_id]["delay_task"] = delay_task
#         verbose(f"started new delay task '{delay_task.get_name()}'")
#
#         m, s = divmod(delay_secs, 60)
#         h, m = divmod(m, 60)
#         d, h = divmod(h, 24)
#         verbose(
#             f"next oob in {channel_desc} will be in {delay_secs}s",
#             f"({d}d {h}h {m}m {s}s)",
#         )
#
#     async def on_ready(self) -> None:
#         """Called when the bot is ready to start."""
#
#         print(f"logged in as {self.user}!")
#         await self.change_presence(status=Status.idle, activity=Game("oob"))
#         for channel_id in self.scheduled_oobs.keys():
#             self.schedule_oob(channel_id)
#
#     async def on_message(self, message: Message) -> None:
#         """Called when a message is sent."""
#
#         # Never respond to our own messages.
#         if message.author == self.user:
#             return
#
#         # Respond immediately if the message is a DM or mentions us.
#         if isinstance(message.channel, DMChannel) or self.user.mentioned_in(message):
#             await self.oob(message.channel, message)
#             return
#
#         # Otherwise, handle the message if it is in $DISCORD_CHANNEL.
#         if message.channel.id in self.scheduled_oobs.keys():
#             # Reduce the delay by DELAY_POW and start a new delayed oob task.
#             self.scheduled_oobs[message.channel.id]["delay_secs"] = int(
#                 self.scheduled_oobs[message.channel.id]["delay_secs"] ** self.DELAY_POW
#             )
#             self.schedule_oob(message.channel.id)


if __name__ == "__main__":
    token = environ["DISCORD_TOKEN"]
    # channels = [
    #     int(channel_str.strip())
    #     for channel_str in environ["DISCORD_CHANNELS"].split(",")
    # ]
    print(f"loaded configuration from environment:")
    print(f"     DISCORD_TOKEN=***")
    # print(f"  DISCORD_CHANNELS={','.join(map(str, channels))}")
    print("connecting to Discord...")
    # OobClient(channels).run(token)
    # RssBot(1080991601502986331, ["https://samasaur1.github.io/feed.xml", "https://eclecticlight.co/category/updates/feed/atom/"]).run(token)
    RssBot(1080991601502986331, []).run(token)