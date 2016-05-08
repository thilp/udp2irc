import argparse
import sys
from collections import namedtuple

import collections
import os
import os.path
import base64

import zlib
from twisted.internet.protocol import DatagramProtocol, ReconnectingClientFactory
from twisted.words.protocols import irc
from twisted.internet import reactor, ssl
from twisted.python import log

DataConsumer = collections.namedtuple('DataConsumer', ['dest_chan', 'encoder'])


class Encoding(object):
    def encode(self, stuff):
        pass


class RawEncoding(Encoding):
    def encode(self, stuff):
        return stuff


class Base64Encoding(Encoding):
    def encode(self, stuff):
        b64_msg = base64.b64encode(stuff)
        return "[{}]{}".format(len(b64_msg), b64_msg)


class GzipBase64Encoding(Base64Encoding):
    def encode(self, stuff):
        return super(GzipBase64Encoding, self).encode(zlib.compress(stuff))


class Echo(DatagramProtocol):
    def __init__(self, ircbot, consumers):
        self.irc = ircbot
        self.consumers = consumers

    def datagramReceived(self, datagram, addr):
        for consumer in self.consumers:
            if self.irc.joined_chans[consumer.dest_chan]:
                self.irc.msg(consumer.dest_chan, consumer.encoder.encode(datagram))
            else:
                log.err('trying to write from %s on non-joined chan %s' % (addr, consumer))


class IrcBot(irc.IRCClient):
    def __init__(self):
        self.bridges = {}
        self.joined_chans = {}

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        log.msg("connected")

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        log.err('connection lost: %s' % reason)
        if hasattr(self, 'bridge'):
            self.bridge.stopListening()

    def identify(self):
        log.msg('identifying as %s' % self.factory.nickname)
        self.msg('NickServ', 'IDENTIFY %s %s' % (self.factory.nickname, self.password))

    def signedOn(self):
        irc.IRCClient.signedOn(self)
        log.msg('signing in as %s' % self.nickname)

        reactor.callLater(5, IrcBot.identify, self)

        log.msg('establishing bridges')
        chan_set = set()  # we want to join each chan only once
        for udp_port, consumers in self.factory.port2consumers.iteritems():
            for consumer in consumers:
                chan_set.add(consumer.dest_chan)
            self.bridges[udp_port] = reactor.listenUDP(udp_port, Echo(self, consumers))

        for chan in chan_set:
            self.join(chan)

    def irc_unknown(self, prefix, command, params):
        log.msg('from network: %s %s %s' % (prefix, command, params))

    def joined(self, channel):
        irc.IRCClient.joined(self, channel)
        log.msg('joining %s' % channel)
        self.joined_chans[channel] = True

    def left(self, channel):
        irc.IRCClient.left(self, channel)
        log.msg('leaving %s' % channel)
        self.joined_chans[channel] = False

    def privmsg(self, user, channel, message):
        irc.IRCClient.privmsg(self, user, channel, message)

        user = user.split('!', 1)[0]

        msg = "I'm just a robot! Please ask a Vikidia sysadmin if you have any question."

        # Check to see if they're sending me a private message
        if channel == self.nickname:
            self.msg(user, msg)
            return

        # Otherwise check to see if it is a message directed at me
        if message.startswith(self.nickname + ":"):
            self.msg(channel, "%s: %s" % (user, msg))

    def irc_ERR_NICKNAMEINUSE(self, prefix, params):
        wanted = self.factory.nickname
        log.msg('GHOSTing %s -> %s' % (self.nickname, wanted))
        self.msg('NickServ', 'GHOST %s %s' % (wanted, self.password))


class IrcBotFactory(ReconnectingClientFactory):
    def __init__(self, port2consumers, nickname, password=None):
        self.port2consumers = port2consumers
        self.nickname = nickname
        self.password = password

    def buildProtocol(self, addr):
        bot = IrcBot()
        bot.factory = self
        bot.nickname = self.nickname
        bot.password = self.password
        return bot

    def clientConnectionLost(self, connector, reason):
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        log.err('IRC connection lost: %s' % reason)
        self.retry(connector)

    def clientConnectionFailed(self, connector, reason):
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)
        log.err('IRC connection failed: %s' % reason)
        log.msg('aborting')
        reactor.stop()


def none(*args):
    return not any(args)

EchoEncoding = collections.namedtuple('EchoEncoding', ['type', 'desc'])


def main():
    ap = argparse.ArgumentParser(description="Make a bridge between a UDP port and an IRC channel.")
    ap.add_argument('--list-encodings', action='store_true', help="List available encodings for --bridge")
    ap.add_argument('--bridge', action='append', help='bridge specification, as "UDPPORT CHAN ENCODING"')
    ap.add_argument('--server', required=True, help='IRC host, as "HOST:PORT"')
    ap.add_argument('--nick', required=True, help="nickname used by the bot on IRC")
    ap.add_argument('--pwd', help="password associated to the nickname, if any")
    ap.add_argument('--tls', action='store_true', help="use a secure IRC connection")
    args = ap.parse_args()

    encodings = {
        'raw': EchoEncoding(type=RawEncoding, desc="No transformation"),
        'b64': EchoEncoding(type=Base64Encoding, desc='M -> "[" + len(base64(M)) + "]" + base64(M)'),
        'z64': EchoEncoding(type=GzipBase64Encoding, desc='like b64, but with a gzip-compressed payload'),
    }

    if args.list_encodings:
        for enc_name, enc in encodings.iteritems():
            print("{}: {}".format(enc_name, enc.desc))
        return

    irc_host, irc_port = args.server.split(':')
    irc_port = int(irc_port)

    port2consumers = {}
    for bridge in args.bridge:
        udp_port, chan_name, enc_name = bridge.split(' ')
        udp_port = int(udp_port)
        if enc_name not in encodings:
            raise RuntimeError("no encoding corresponding to {} (see --list-encodings)".format(enc_name))
        enc = encodings[enc_name]
        consumer = DataConsumer(dest_chan=chan_name, encoder=enc.type())
        if udp_port not in port2consumers:
            port2consumers[udp_port] = [consumer]
        else:
            port2consumers[udp_port].append(consumer)

    f = IrcBotFactory(port2consumers, args.nick, args.pwd)

    if args.tls:
        cf = ssl.optionsForClientTLS(unicode(irc_host))
        reactor.connectSSL(irc_host, irc_port, f, cf)
    else:
        reactor.connectTCP(irc_host, irc_port, f)

    log.startLogging(sys.stdout)

    lockfile = '/tmp/udp2irc_lockfile'
    if os.path.exists(lockfile):
        log.err("Won't run until %s exists!" % lockfile)
    else:
        with open(lockfile, mode='w') as f:
            f.write(str(os.getpid()))
        try:
            reactor.run()
        finally:
            os.remove(lockfile)


if __name__ == '__main__':
    main()
