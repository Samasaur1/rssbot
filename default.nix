{ lib, writers, python3Packages }:

(writers.writePython3Bin "rssbot" {
  libraries = with python3Packages; [
    (discordpy.override { withVoice = false; })
    feedparser
    validators
  ];
  flakeIgnore = [ "E261" "E262" "E302" "E501" "E722" "F541" "W292" ];
} (builtins.readFile ./rssbot.py)) // {
  meta = with lib; {
    description = "A Discord bot that watches RSS feeds";
    homepage = "https://github.com/Samasaur1/rssbot";
  };
}
