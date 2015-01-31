from twisted.internet.protocol import DatagramProtocol, ClientFactory
from twisted.words.protocols import irc
from twisted.internet import reactor

import logging

class Echo(DatagramProtocol):
    def __init__(self, ircbot):
        self.irc = ircbot

    def datagramReceived(self, datagram, (host, port)):
        print('Received %s from %s:%d' % (datagram, host, port))
        self.transport.write(datagram, (host, port))
        self.irc.msg(self.irc.factory.channel, datagram)


class IrcBot(irc.IRCClient):
    factory = None
    nickname = None
    port = None

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        logger = logging.getLogger(__name__)
        logger.info('now connected')

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        logger = logging.getLogger(__name__)
        logger.info('disconnected: %s' % reason)
        self.bridge.stopListening()

    def signedOn(self):
        irc.IRCClient.signedOn(self)
        logger = logging.getLogger(__name__)
        logger.info('now logged as ' + self.nickname)
        self.join(self.factory.channel)
        self.bridge = reactor.listenUDP(self.factory.udp_port, Echo(self))

    def joined(self, channel):
        irc.IRCClient.joined(self, channel)
        logger = logging.getLogger(__name__)
        logger.info('just joined %s' % channel)

    def privmsg(self, user, channel, message):
        irc.IRCClient.privmsg(self, user, channel, message)
        logger = logging.getLogger(__name__)
        logger.info('%s on %s: %s' % (user, channel, message))

        user = user.split('!', 1)[0]

        # Check to see if they're sending me a private message
        if channel == self.nickname:
            msg = "It isn't nice to whisper!  Play nice with the group."
            self.msg(user, msg)
            return

        # Otherwise check to see if it is a message directed at me
        if message.startswith(self.nickname + ":"):
            msg = "%s: I am a log bot" % user
            self.msg(channel, msg)
            logger = logging.getLogger(__name__)
            logger.info("<%s> %s" % (self.nickname, msg))

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
        logger = logging.getLogger(__name__)
        logger.info("disconnected: %s" % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print("IRC connection failed: %s" % reason)
        reactor.stop()


if __name__ == '__main__':
    f = IrcBotFactory(9999, '#vikidia-rc')
    reactor.connectTCP('chat.freenode.net', 6667, f)
    reactor.run()