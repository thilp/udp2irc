import argparse

from twisted.internet.protocol import DatagramProtocol, ClientFactory
from twisted.words.protocols import irc
from twisted.internet import reactor


class Echo(DatagramProtocol):
    def __init__(self, ircbot):
        self.irc = ircbot

    def datagramReceived(self, datagram, (host, port)):
        self.irc.msg(self.irc.factory.channel, datagram)


class IrcBot(irc.IRCClient):
    factory = None
    nickname = None
    port = None

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.bridge.stopListening()

    def signedOn(self):
        irc.IRCClient.signedOn(self)
        self.join(self.factory.channel)
        self.bridge = reactor.listenUDP(self.factory.udp_port, Echo(self))

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


class IrcBotFactory(ClientFactory):
    def __init__(self, udp_port, channel, bot_nick='hermes'):
        self.udp_port = udp_port
        self.channel = channel
        self.nickname = bot_nick

    def buildProtocol(self, addr):
        bot = IrcBot()
        bot.factory = self
        bot.nickname = self.nickname
        return bot

    def clientConnectionLost(self, connector, reason):
        """Automatic reconnection"""
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print("IRC connection failed: %s" % reason)
        reactor.stop()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Make a bridge between a UDP port and an IRC channel.")
    ap.add_argument('udpport', type=int)
    ap.add_argument('channel', default='#vikidia-rc')
    ap.add_argument('--server', default='chat.freenode.net')
    ap.add_argument('--serverport', type=int, default=6667)
    args = ap.parse_args()

    f = IrcBotFactory(args.udpport, args.channel)
    reactor.connectTCP(args.server, args.serverport, f)
    reactor.run()