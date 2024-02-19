import json
import os
from datetime import datetime, timezone, timedelta
import hashlib
from asyncio import sleep, create_task
from os import environ
from random import randrange
from typing import List, Optional, Dict

import discord.utils
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
    @classmethod
    def from_dict(cls, **kwargs):
        self = cls(kwargs['url'])
        self.etag = kwargs['etag']
        self.modified = kwargs['modified']
        self.previous_entry = Entry(kwargs['previous_entry'])
        return self

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
            try:
                d = feedparser.parse(self.url, etag=self.etag, modified=self.modified)
            except:
                print("ERR: feedparser.parse errored!")
                print(self.url)
                print(self.previous_entry)
                print(self.etag)
                print(self.modified)
                return None
            if d is None:
                print("ERR: d is None")
                print(self.url)
                print(self.previous_entry)
                print(self.etag)
                print(self.modified)
            if not hasattr(d, "status"):
                print("ERR: no status attribute")
                print(self.url)
                print(self.previous_entry)
                print(self.etag)
                print(self.modified)
                print(d)
                return None
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


def migration(feeds):
    # migrate from Dict[str, List[int]] to Dict[str, Dict[int, List[str]]]
    # was { feed -> [ channel ] }
    # to: { feed -> { channel -> [ filter ] } }
    if not isinstance(feeds, dict):
        return {}
    processed_feeds = {}
    for k, v in feeds.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, list):
            channel_dict = {}
            for channel in v:
                if not isinstance(channel, int):
                    continue
                channel_dict[channel] = []
            processed_feeds[k] = channel_dict
        if isinstance(v, dict):
            # for channel, filters in v:
            #     if not isinstance(channel, int):
            #         continue
            #     if not isinstance(filters, list):
            #         continue
            # return
            processed_feeds[k] = { int(channel): [f for f in filters if isinstance(f, str)] for channel, filters in v.items() if (isinstance(channel, int) or isinstance(channel, str)) and isinstance(filters, list)}
    return processed_feeds

class RssBot(Client):
    def __init__(self, feeds: Dict[str, Dict[int, List[str]]], feed_data: Dict[str, FeedData], **options) -> None:
        super().__init__(intents=Intents(guilds=True, messages=True), **options)
        # { feed -> { channel -> [ filter ] } }
        self.feeds: Dict[str, Dict[int, List[str]]] = migration(feeds)
        self.feed_data: Dict[str, FeedData] = feed_data
        self.task = None
        self.ADMIN_UID = int(os.getenv('ADMIN_UID', 377776843425841153))
        self.DEBUG_CHANNEL = int(os.getenv('DEBUG_CHANNEL', 1080991601502986331))

    async def notify(self, msg: str) -> None:
        await self.get_channel(self.DEBUG_CHANNEL).send(msg)

    def dump_feeds_to_file(self):
        verbose("Updating dump files")
        with open("feeds.json", "w") as file:
            json.dump(self.feeds, file, default=lambda o: o.__dict__, sort_keys=True, indent=4)
        with open("feeddata.json", "w") as file:
            json.dump(self.feed_data, file, default=lambda o: o.__dict__, sort_keys=True, indent=4)

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

        await self.notify("Now running")

    async def on_message(self, message: Message) -> None:
        """Called when a message is sent."""

        # Never respond to our own messages.
        if message.author == self.user:
            return

        if not self.user.mentioned_in(message):
            return

        if "<@1080989856248893521>" not in message.content:
            return  # A reply to us that doesn't tag us

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

        msg = message.content.split(">", maxsplit=1)[1].strip(" ")
        _msg = msg.split(" ", maxsplit=1)
        cmd = _msg[0]
        if cmd == "add":
            url = _msg[1]
            log(f"Request to add '{url}'")
            if url in self.feeds:
                if message.channel.id in self.feeds[url]:
                    print("Already watching feed in channel")
                    await say(message, f"Already watching {url} in this channel")
                else:
                    self.feeds[url][message.channel.id] = []
                    print("Now watching feed (existing feed)")
                    self.dump_feeds_to_file()
                    await say(message, f"Now watching {url} in this channel")
            else:
                if validators.url(url):
                    self.feeds[url] = { message.channel.id: [] }
                    print("Now watching feed (new feed)")
                    self.dump_feeds_to_file()
                    await self.update_status()
                    await say(message, f"Now watching {url} in this channel")
                else:
                    print("Invalid URL")
                    await say(message, f"Not a valid URL")
        elif cmd == "remove":
            url = _msg[1]
            log(f"Request to remove '{url}'")
            if url in self.feeds and message.channel.id in self.feeds[url]:
                del self.feeds[url][message.channel_id]
                print("Found")
                if len(self.feeds[url]) == 0:
                    del self.feeds[url]
                    print("Was last url for feed, so feed is removed")
                    await self.update_status()
                self.dump_feeds_to_file()
                await say(message, f"Removed {url} from the feeds for this channel")
            else:
                await say(message, f"Could not find {url} in the feeds for this channel")
                print("Not found")
        elif cmd == "list":
            log(f"Request to list feeds")
            feeds_in_channel = []
            for feed in self.feeds:
                if message.channel.id in self.feeds[feed]:
                    feeds_in_channel.append(f"{feed} (filters: {len(self.feeds[feed][message.channel_id])})")
            if len(feeds_in_channel) == 0:
                await say(message, "No feeds in this channel")
                return
            fstr = "\n".join(feeds_in_channel)
            await say(message, f"""
**Feeds in this channel**:
{fstr}
""", 5)
        elif cmd == "help" or cmd == "-h":
            log(f"Request for help")
            await say(message, """
To add a feed, try "<@1080989856248893521> add https://samasaur1.github.io/feed.xml"
To remove a feed, try "<@1080989856248893521> remove https://samasaur1.github.io/feed.xml"
To list all feeds in this channel, try "<@1080989856248893521> list"
To get help about filters, try "<@1080989856248893521> filter help"
""", 5)
        elif cmd == "filter":
            submsg = _msg.split(" ", maxsplit=2)
            subcmd = submsg[0]
            if subcmd == "list":
                feed = submsg[1]
                log(f"Request to list filters on '{feed}'")
                if not feed in self.feeds:
                    print("Feed not in channel")
                    await say(message, "That feed does not exist in this channel, so it cannot have filters")
                if len(self.feeds[feed][message.channel_id]) == 0:
                    await say(message, "No filters on feed in this channel")
                    return
                output = ""
                # for idx, filter in enumerate(self.feeds[feed][message.channel_id]):
                #     output.append(f"{idx}: `{filter}`")
                for f in self.feeds[feed][message.channel_id]:
                    output.append(f"- `{filter}`\n")
                await say(message, output)
            elif subcmd == "add":
                feed = submsg[1]
                new_filter = submsg[2]
                log(f"Request to add filter `{new_filter}` on '{feed}'")
                if not feed in self.feeds:
                    print("Feed not in channel")
                    await say(message, "That feed does not exist in this channel, so it cannot have filters")
                if new_filter in self.feeds[feed][message.channel_id]:
                    print("Filter already exists on feed in channel")
                    await say(message, "Filter already exists on that feed in this channel")
                else:
                    self.feeds[feed][message.channel_id].append(new_filter)
                    print("Filter added")
                    self.dump_feeds_to_file()
                    await say(message, "Filter now applies to that feed in this channel")
            elif subcmd == "remove":
                feed = submsg[1]
                old_filter = submsg[2]
                log(f"Request to remove filter `{old_filter}` on '{feed}'")
                if not feed in self.feeds:
                    print("Feed not in channel")
                    await say(message, "That feed does not exist in this channel, so it cannot have filters")
                if old_filter in self.feeds[feed][message.channel_id]:
                    self.feeds[feed][message.channel_id].remove(old_filter)
                    print("Found")
                    self.dump_feeds_to_file()
                    await say(message, "Filter no longer applies to that feed in this channel")
                else:
                    print("Not found")
                    await say(message, "No matching filter on that feed in this channel")
            elif subcmd == "help":
                log("Request for filter help")
                await say(message, """
                **Filters** are strings, configurable per feed by channel. If a new post matches any of the existing filters, the post will not be posted in that channel.
                To list filters on a feed (in the current channel), try "<@1080989856248893521> filter list https://samasaur1.github.io/feed.xml".
                To add a filter on a feed, try "<@1080989856248893521> filter add https://samasaur1.github.io/feed.xml some multi-word filter I don't want to see posts about" (no quotes are required)
                To add a filter on a feed, try "<@1080989856248893521> filter remove https://samasaur1.github.io/feed.xml some filter I once added, but now want to see posts about again" (no quotes are required)
                """, 5)
            else:
                log("Unknown filter subcommand")
                await say(message, "Unknown subcommand (try \"<@1080989856248893521> filter help\")")
        elif cmd == "oob":
            log(f"Request to oob")
            await say(message, "<@937855314290692187>") #@oobot
        elif cmd == "status":
            log(f"Request for status")
            if message.author.id != self.ADMIN_UID:
                await say(message, "Unauthorized user")
                return
            td = datetime.now(timezone.utc) - self.last_check

            def desc(id: int):
                # This should work, but it doesn't for some reason
                # chan = self.get_channel(id)
                # if isinstance(chan, DMChannel):
                #     return f"DM with {chan.recipient}"
                # elif isinstance(chan, GroupChannel):
                #     return f"Group DM{f' named {chan.name}' if chan.name else ''} with [{', '.joined(map(lambda user: user.name, chan.recipients))}]"
                # else:
                #     return f"#{chan.name} in {chan.guild.name}"
                return f"<#{id}>"
            s = f"""
**Status:**
Time since last check: {td}
Estimated time until next check (approximate): {timedelta(seconds=RSS_FETCH_INTERVAL - td.total_seconds())}
Feeds being watched: {list(self.feeds.keys())}
Channels with feeds: {', '.join({desc(channel) for channels in self.feeds.values() for channel in channels})}
"""
            await say(message, s, 1)
        elif cmd == "forcerefresh":
            log(f"Request to forcerefresh")
            if message.author.id != self.ADMIN_UID:
                await say(message, "Unauthorized user")
                return
            self.schedule_updates()
        elif cmd == "prune":
            log("Request to prune")
            if message.author.id != self.ADMIN_UID:
                await say(message, "Unauthorized user")
                return
            pruned_channels = set()
            pruned_feeds = set()
            needs_status_update = False
            for feed in self.feeds:
                for channel_id in self.feeds[feed]:
                    if self.get_channel(channel_id) is None:
                        del self.feeds[feed][channel_id]
                        pruned_channels.add(channel_id)
                if len(self.feeds[feed]) == 0:
                    pruned_feeds.add(feed)
                    needs_status_update = True
            for feed in pruned_feeds:
                del self.feeds[feed]
            verbose(f"Pruned [{', '.join((str(x) for x in pruned_channels))}]")
            if needs_status_update:
                verbose(f"...which pruned [{', '.join(pruned_feeds)}]")
                await self.update_status()
            pc = f"{len(pruned_channels)} channel{'s' if len(pruned_channels) != 1 else ''}"
            pf = f", {len(pruned_feeds)} feed{'s' if len(pruned_feeds) != 1 else ''}" if needs_status_update else ""
            await say(message, f"Pruned {pc}{pf}")
        elif cmd == "reactwith":
            log("Request to add reaction to message")
            if message.author.id != 377776843425841153:
                await say(message, "Unauthorized user")
                return
            print(msg)
            args = [x for x in _msg[1].split(" ") if x != ""]
            if len(args) < 2:
                await say(message, "Missing arguments")
                return

            if len(args) == 2:
                chan = message.channel
            else: #len(args) == 3:
                chan = self.get_channel(int(args[2]))
            verbose(f"Got channel {chan} with name {chan.name if chan.name else '{}'}")

            if args[0].startswith("<:") and args[0].endswith(">"):
                react_emoji = args[0]
            elif all(ord(c) < 128 for c in args[0]):
                react_emoji = discord.utils.get(chan.guild.emojis, name=args[0])
            else:
                react_emoji = args[0]
            verbose(f"Got emoji {react_emoji} with name {args[0]}")
            react_message = await chan.fetch_message(int(args[1]))
            verbose(f"Got message {react_message} with id {args[1]}")
            await react_message.add_reaction(react_emoji)
        else:
            if message.author.id == 268838716259172374:
                if cmd.startswith("hi") or cmd == "hello" or cmd == "hey":
                    await say(message, "hi alex!")
                    return
                elif cmd == "ily":
                    await say(message, "ily too!")
                    return
                else:
                    await say(message, "sorry, bestie, i don't understand")
                    return
            log(f"Unknown command")
            await say(message, "Unknown command (try \"<@1080989856248893521> help\")")

    def censored_by(entry, filters):
        output = entry.output()
        for f in filters:
            if f in output:
                verbose(f"entry {output} censored by {f}")
                return True
        return False
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
                    if entries is None:
                        await self.notify(f"Error! Feed {feed} could not be reached!")
                        continue
                    verbose(f"{len(entries)} entries")
                    if len(entries) == 0:
                        continue
                    for entry in entries:
                        print(f"New post on {feed}: {entry.output()}")

                    for channel_id in self.feeds[feed]:
                        filters = self.feeds[feed][channel_id]
                        chan_entries = [entry for entry in entries if not censored_by(entry, filters)]
                        if len(chan_entries) == 0:
                            verbose(f"All entries in channel {channel_id} censored")
                            continue
                        channel = self.get_channel(channel_id)
                        if not channel:
                            # Consider automatically removing this channel?
                            print(f"ERR: Cannot get channel <#{channel_id}> to update {feed}")
                            await self.notify(f"Error! Cannot get channel <#{channel_id}> to update {feed}")
                            continue
                        async with channel.typing():
                            await sleep(randrange(1, 3))
                            for entry in chan_entries:
                                await channel.send(f"New post from {feed}:\n{entry.output()}")
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    await self.notify(f"Unexpected {err=}, {type(err)=}")
                    raise

            self.dump_feeds_to_file()
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
    print(f"...verbose={'VERBOSE' in environ.keys()}")
    print(f"...debug channel={os.getenv('DEBUG_CHANNEL', '1080991601502986331 (default)')}")
    print(f"...admin UID={os.getenv('ADMIN_UID', '377776843425841153 (default)')}")
    print("searching for feed files in working directory")
    try:
        with open("feeds.json", "r") as file:
            feeds = json.load(file)
            print("...loaded feeds")
    except:
        print("...feeds not found")
        feeds = {}
    try:
        with open("feeddata.json", "r") as file:
            feed_data = json.load(file)
            print("...loaded feed data")
    except:
        print("...feed data not found")
        feed_data = {}
    feed_data = {feed: FeedData.from_dict(**feed_data[feed]) for feed in feed_data.keys()}
    print("connecting to Discord...")
    RssBot(feeds, feed_data).run(token)
