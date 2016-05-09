# udp2irc

The `hermes.py` script is used on the [Vikidia](https://vikidia.org) wikis to report each change on our IRC channels.
Thus, it provides:

1. A way for IRC users to patrol efficiently, with **real-time data** and whatever notification system their IRC client offers.
1. **Machine-readable**, live data for bots.

## Usage

```
hermes.py [-h] [--list-encodings] [--bridge BRIDGE] --server SERVER
          --nick NICK [--pwd PWD] [--tls]

Make a bridge between a UDP port and an IRC channel.

optional arguments:
  -h, --help        show this help message and exit
  --list-encodings  List available encodings for --bridge
  --bridge BRIDGE   bridge specification, as "UDPPORT CHAN ENCODING"
  --server SERVER   IRC host, as "HOST:PORT"
  --nick NICK       nickname used by the bot on IRC
  --pwd PWD         password associated to the nickname, if any
  --tls             use a secure IRC connection
```

### Bridges

A “bridge” is the way you tell hermes what to transmit, where, and how.
**Multiple bridges** may be specified.
Bridges have 3 components:

1. **A source UDP port:** The port on which hermes will listen for new data from MediaWiki.
   Example: `9999`
1. **A destination channel:** The IRC channel where hermes will write what it reads on the source UDP port.
   Example: `#vikidia-recentchanges`
1. **An encoding:** How the data is to be transformed before transmission.
   Supported encoding modes can be displayed _via_ the `--list-encodings` options.
   Example: `raw`

These 3 components, once joined together with spaces, form a bridge specification
that can be given to hermes' `--bridge` option. For example: `--bridge "9999 #vikidia-recentchanges raw"`

### Encodings

* **raw:** The identity function: no transformation, what is read from MediaWiki is directly written
  to the appropriate IRC channels.
  Formula: `raw(X) = X`
* **b64:** The input is converted to [base64](https://en.wikipedia.org/wiki/Base64), prefixed with its own length,
  and delimited by square brackets.
  This makes it easier (especially for bots) to process messages when these are broken into chunks, as is often the case
  on IRC.
  Formula: `b64(X) = "[" + length(base64(X)) + ":" + base64(X) + "]"`
* **z64:** Identical to _b64_, except that the payload is [compressed](https://en.wikipedia.org/wiki/DEFLATE)
  before base64-encoding. This allows smaller message sizes (and thus less chunks) on IRC.
  Formula: `z64(X) = "[" + length(base64(deflate(X))) + ":" + base64(deflate(X)) + "]"`

More efficient encodings than base64 (e.g. base85) and compression algorithms than DEFLATE (e.g. snappy) could have been used,
but they would probably be far less common. It is likely that, whatever language you write your bot in,
it has libraries for base64 and DEFLATE (often under the name “gzip”).

#### Decoding z64

The above encodings are performed using the tools provided by Python's standard library.
As such, trying to decode data encoded with them may prove difficult:

```
$ base64 -d data-encoded-with-z64 | zcat
gzip: stdin: not in gzip format
```

This particular gzip-related problem above is due to Python's
[`zlib.compress`](https://docs.python.org/2/library/zlib.html#zlib.compress) not adding an expected gzip header
to the data (gzip being a file format _around_ the DEFLATE compression).

To decode _z64_-encoded data in other languages than Python, please have a look at
[this StackOverflow question](https://stackoverflow.com/questions/3178566/deflate-command-line-tool).
If you are using Python, then [`zlib.decompress`](https://docs.python.org/2/library/zlib.html#zlib.decompress) will do.

Don't forget to base64-decode first!

### Example service file

You can use a variation of this file to manage your hermes daemon with [systemd](https://en.wikipedia.org/wiki/Systemd):

```systemd
[Unit]
Description=Bridge between MediaWiki's UDP stream for recent changes and IRC
After=apache2.service

[Service]
User=udp2irc
ExecStart=/usr/bin/python /path/to/hermes.py \
          --bridge '9999 #vikidia-recentchanges raw' \
          --bridge '9998 #vikidia-rc-json raw' \
          --bridge '9998 #vikidia-rc-z64 z64' \
          --server chat.freenode.net:6697 --tls \
          --nick 'Bifrost' --pwd '...'
Restart=always
RestartSec=1min
OOMScoreAdjust=200

[Install]
WantedBy=multi-user.target
```

## How it works

MediaWiki advertises each new change [via UDP](https://www.mediawiki.org/wiki/Manual:$wgRCFeeds).
The `hermes.py` script simply listens to what MediaWiki says and repeats it (possibly transformed) on IRC.
