import argparse
import sys
import os
import os.path

from twisted.internet.protocol import DatagramProtocol, ReconnectingClientFactory
from twisted.words.protocols import irc
from twisted.internet import reactor, ssl
from twisted.python import log


class Echo(DatagramProtocol):
    def __init__(self, ircbot, chans):
        self.irc = ircbot
        self.chans = chans

    def datagramReceived(self, datagram, addr):
        for chan in self.chans:
            if self.irc.joined[chan]:
                self.irc.msg(chan, datagram)
            else:
                log.err('trying to write from %s on non-joined chan %s' % (addr, chan))


class IrcBot(irc.IRCClient):
    def __init__(self):
        self.bridges = {}
        self.joined = {}

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
        for port, chans in self.factory.ports2chans:
            chan_set.add(*chans)
            self.bridges[port] = reactor.listenUDP(port, Echo(self, chans))

        for chan in chan_set:
            self.join(chan)

    def irc_unknown(self, prefix, command, params):
        log.msg('from network: %s %s %s' % (prefix, command, params))

    def joined(self, channel):
        irc.IRCClient.joined(self, channel)
        log.msg('joining %s' % channel)
        self.joined[channel] = True

    def left(self, channel):
        irc.IRCClient.left(self, channel)
        log.msg('leaving %s' % channel)
        self.joined[channel] = False

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
    def __init__(self, ports2chans, nickname, password=None):
        self.ports2chans = port2chans
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


def main():
    ap = argparse.ArgumentParser(description="Make a bridge between a UDP port and an IRC channel.")
    ap.add_argument('--human-udp', type=int, help="port where to read UDP packets for human-readable data")
    ap.add_argument('--json-udp', type=int, help="port where to read UDP packets for JSON data")
    ap.add_argument('--server', required=True, help='IRC host, as "HOST:PORT"')
    ap.add_argument('--human-chan', action='append', help="IRC channels for human-readable output (use multiple times)")
    ap.add_argument('--json-chan', action='append', help="IRC channels for JSON output (use multiple times)")
    ap.add_argument('--nick', required=True, help="nickname used by the bot on IRC")
    ap.add_argument('--pwd', help="password associated to the nickname, if any")
    ap.add_argument('--tls', action='store_true', help="use a secure IRC connection")
    args = ap.parse_args()

    irc_host, irc_port = args.server.split(':')
    irc_port = int(irc_port)

    if none(args.human_udp, args.json_udp):
        raise RuntimeError('no UDP port provided')

    port2chans = zip([args.human_udp, args.json_udp], [args.human_chan, args.json_chan])
    for port, chans in port2chans:
        if port is None and chans:
            raise RuntimeError('no UDP port corresponding to IRC chans %s' % ', '.join(chans))
        if port and not chans:
            raise RuntimeError('no IRC chans corresponding to UDP port %s' % port)

    f = IrcBotFactory(port2chans, args.nickname, args.pwd)

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