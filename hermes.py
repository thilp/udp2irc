import argparse
import sys
import os, os.path

from twisted.internet.protocol import DatagramProtocol, ClientFactory
from twisted.words.protocols import irc
from twisted.internet import reactor, ssl
from twisted.python import log


class Echo(DatagramProtocol):
    def __init__(self, ircbot):
        self.irc = ircbot

    def datagramReceived(self, datagram, addr):
        chans = self.irc.factory.channels
        for chan in filter(lambda k: chans[k], chans):
            self.irc.msg(chan, datagram)


class IrcBot(irc.IRCClient):
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

        for chan in self.factory.channels:
            self.join(chan)

        log.msg('establishing bridge')
        self.bridge = reactor.listenUDP(self.factory.udp_port, Echo(self))

    def irc_unknown(self, prefix, command, params):
        log.msg('from network: %s %s %s' % (prefix, command, params))

    def joined(self, channel):
        irc.IRCClient.joined(self, channel)
        log.msg('joining %s' % channel)
        self.factory.channels[channel] = True

    def left(self, channel):
        irc.IRCClient.left(self, channel)
        log.msg('leaving %s' % channel)
        self.factory.channels[channel] = False

    def privmsg(self, user, channel, message):
        irc.IRCClient.privmsg(self, user, channel, message)

        user = user.split('!', 1)[0]

        # Check to see if they're sending me a private message
        if channel == self.nickname:
            msg = "I'm just a robot! Please ask a Vikidia sysadmin if you have any question."
            self.msg(user, msg)
            return

        # Otherwise check to see if it is a message directed at me
        if message.startswith(self.nickname + ":"):
            msg = "%s: I'm just a robot! Please ask a Vikidia sysadmin if you have any question." % user
            self.msg(channel, msg)

    def irc_ERR_NICKNAMEINUSE(self, prefix, params):
        wanted = self.factory.nickname
        log.msg('GHOSTing %s -> %s' % (self.nickname, wanted))
        self.msg('NickServ', 'GHOST %s %s' % (wanted, self.password))


class IrcBotFactory(ClientFactory):
    def __init__(self, udp_port, channels, nickname, password=None):
        self.udp_port = udp_port
        self.channels = dict(zip(channels, map(lambda _: False, channels)))
        self.nickname = nickname
        self.password = password

    def buildProtocol(self, addr):
        bot = IrcBot()
        bot.factory = self
        bot.nickname = self.nickname
        bot.password = self.password
        return bot

    def clientConnectionLost(self, connector, reason):
        """Automatic reconnection"""
        log.err('IRC connection lost: %s' % reason)
        log.msg('reconnecting ...')
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        log.err('IRC connection failed: %s' % reason)
        log.msg('aborting')
        reactor.stop()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Make a bridge between a UDP port and an IRC channel.")
    ap.add_argument('--udp', type=int, required=True, help="port where to read UDP packets")
    ap.add_argument('--server', required=True, help='IRC host, as "HOST:PORT"')
    ap.add_argument('--chan', action='append', required=True, help="IRC channels to visit (usable multiple times)")
    ap.add_argument('--nick', required=True, help="nickname used by the bot on IRC")
    ap.add_argument('--pwd', help="password associated to the nickname, if any")
    ap.add_argument('--tls', action='store_true', help="use a secure connection")
    args = ap.parse_args()

    irc_host, irc_port = args.server.split(':')
    irc_port = int(irc_port)

    f = IrcBotFactory(args.udp, args.chan, args.nick, args.pwd)

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
