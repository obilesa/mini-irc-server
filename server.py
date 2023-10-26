import socket
import re
import logging
import _thread
import sys
import time
from dataclasses import dataclass, field

nick_regex = re.compile("^[][`_^{|}A-Za-z][][`_^{|}A-Za-z0-9-]{0,50}$")
channel_regex = re.compile("^[&#+!][^\x00\x07\x0a\x0d ,:]{0,50}$")

logging.getLogger().setLevel(logging.INFO)


def parse(data):
    data = data.decode("utf-8")
    commands = data.split("\r\n")
    return commands


class Server(object):
    """
        This class is a representation of an irc server it is responsible for handling all the commands and sending
        the correct responses to the client

            Attributes:
                _keywords: A dictionary of commands available on the server and their corresponding functions (command->function)
                _clients: A dictionary of clients connected to the server (socket->Client)
                _channels: A dictionary of channels on the server (channel_name->Channel)
                _hostname: The hostname of the server
                _serverip: The ip address of the server
                _server_port: The port the server is listening on
                _start_date: The date the server was started
            """

    def __init__(self):

        self.keywords = {"NICK": self.nick,
                         "JOIN": self.join,
                         "TOPIC": self.topic,
                         "NAMES": self.names,
                         "USER": self.user,
                         "CAP": self.cap,
                         "MODE": self.mode,
                         "PING": self.ping,
                         "PONG": self.pong,
                         "QUIT": self.quit,
                         "PRIVMSG": self.privmsg,
                         "WHO": self.who,
                         "WHOIS": self.whois,
                         "PART": self.part}
        self._server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self._clients = {}
        self._channels = {}
        self._hostname = socket.getfqdn()
        self._server_port = 6667
        self._serverip = socket.getaddrinfo(socket.gethostname(), self._server_port, socket.AF_INET6)[0][4][0]
        self.start_date = time.strftime("%Y-%m-%d", time.gmtime())

    def start(self):
        logging.info(f"Starting server on {self._serverip}:{self._server_port}")
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._serverip, self._server_port))
        self._server.listen()
        self.run()

    def run(self):
        """
            Runs the server and listens for new connections, starts a new thread for each new connection

        Returns:
            None
        """
        while True:
            try:
                client, address = self._server.accept()
                client.settimeout(180)
                logging.info(f"New connection from {address}")
                self._clients[client] = Client()
                _thread.start_new_thread(self.multi_thread_client, (client,))

            except socket.error as e:
                logging.error(e)

    def multi_thread_client(self, client: socket.socket):
        """
            Handles the client and listens for new commands
        Args:
            client: the socket of the client

        Returns:
            None
        """
        sent_greeting = False
        while client in self._clients:

            if self._clients[client].nick and self._clients[client].real_name and self._clients[
                client].username and not sent_greeting:
                client.send(
                    f":{self._hostname} 001 {self._clients[client].nick} :Hi, welcome to IRC {self._clients[client].nick}\r\n".encode())
                client.send(
                    f":{self._hostname} 003 {self._clients[client].nick} :This server was created {self.start_date} \r\n".encode())
                client.send(
                    f":{self._hostname} 004 {self._clients[client].nick} {self._hostname} 0.01 o o\r\n".encode())
                client.send(
                    f":{self._hostname} 251 {self._clients[client].nick} :There are {len(self._clients)} users and 0 services on 1 server \r\n".encode())
                sent_greeting = True

            try:
                data = client.recv(4096)
                logging.info(data)
                if data:
                    commands = parse(data)
                    for command in list(filter(None, commands)):
                        self.handle(command, client)

                else:
                    logging.info(f"Client {self._clients[client].nick} disconnected")
                    client.close()
                    del self._clients[client]
            except socket.timeout as e:
                self.quit(["QUIT", "Client timed out"], client)
                return
            except socket.error as e:
                pass

    def sendall(self, data: str):
        for client in self._clients:
            client.send(data.encode())

    def nick(self, command: list[str], client: socket.socket):
        """
        This function changes the nickname of the client
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None

        """
        if len(command) == 1:
            client.send(f":{self._hostname} 431 {self._clients[client].nick} :No nickname given\r\n".encode())
        if nick_regex.match(command[1]):
            for _client in self._clients.values():
                if _client.nick == command[1]:
                    client.send(
                        f":{self._hostname} 433 {_client.nick} {command[1]} :Nickname is already in use\r\n".encode())
                    return
            self._clients[client].nick = command[1]
        else:
            client.send(
                f":{self._hostname} 432 {self._clients[client].nick} {command[1]} :Erroneous nickname\r\n".encode())

    def user(self, command: list[str], client: socket.socket):
        """
        This function sets the username and real name of the client
        Args:
            command: The command received from the
            client:  The socket of the client

        Returns:
             None

        """
        if not self._clients[client].username:
            if re.compile("^USER ([A-z0-9]*) 0 \* :[a-z A-Z0-9]+$").match(" ".join(command)):
                self._clients[client].username = command[1]
                self._clients[client].real_name = command[4][1:] + " " + " ".join(command[4:]) if len(command) > 5 else \
                    command[4][1:]

            else:
                if self._clients[client].nick:
                    client.send(f"{self._hostname} 461 * USER :Not enough parameters\r\n".encode())
                else:
                    client.send(
                        f"{self._hostname} 461 {self._clients[client].nick} USER :Not enough parameters\r\n".encode())
        else:
            client.send("{self._hostname} 462 * :You may not reregister\r\n".encode())

    def join(self, command: list[str], client: socket.socket):
        """
        This function makes the client join a channel
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
             None

        """
        if channel_regex.match(command[1]):
            if command[1] not in self._channels:
                self._channels[command[1]] = Channel()

            self._channels[command[1]].clients.append(client)
            self._clients[client].join_channel(command[1])
            client.send(
                f":{self._clients[client].nick}!{self._clients[client].username}@::1 JOIN {command[1]}\r\n".encode())
            self.topic(["TOPIC", command[1]], client)
            self.names(["NAMES", command[1]], client)
            for _client in self._channels[command[1]].clients:
                if _client != client:
                    _client.send(
                        f":{self._clients[client].nick}!{self._clients[client].username}@::1 JOIN {command[1]}\r\n".encode())
        else:
            client.send(f"{self._hostname} 403 {self._clients[client].nick} {command[1]}: No such channel\r\n".encode())

    def quit(self, command: list[str], client: socket.socket):
        """
        This function removes the client from the server and notifies the other clients about the leaving client
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        for channel in self._channels.values():
            if client in channel.clients:
                channel.clients.remove(client)

        for _client in self._clients:
            if _client != client:
                _client.send(
                    f":{self._clients[client].nick}!{self._clients[client].username}@::1 QUIT :{command[1]}\r\n".encode())

        del self._clients[client]
        client.close()

    def ping(self, command: list[str], client: socket.socket):
        """
        This function answers to a ping request
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        client.send(f":{self._hostname} PONG {self._hostname} :{command[1]}\r\n".encode())

    def pong(self, command, client):
        pass

    def who(self, command: list[str], client: socket.socket):
        """
        This function returns information about the clients on a channel
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        if command[1] in self._channels:
            for client in self._channels[command[1]].clients:
                client.send(
                    f":{self._hostname} 352 {self._clients[client].nick} {command[1]} {self._clients[client].username} ::1 {self._hostname} {self._clients[client].nick} H :0 {self._clients[client].real_name}\r\n".encode())

            client.send(
                f":{self._hostname} 315 {self._clients[client].nick} {command[1]} :End of WHO list.\r\n".encode())
        else:
            client.send(f"No such channel {command[1]}\r\n")

    def topic(self, command: list[str], client: socket.socket):
        """
        This function sets the topic of a channel on the server
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        if client in self._channels[command[1]].clients:
            if len(command) == 2:
                if self._channels[command[1]].topic:
                    client.send(
                        f":{self._hostname} 332 {self._clients[client].nick} {command[1]} :{self._channels[command[1]].topic}\r\n".encode())
                else:
                    client.send(
                        f":{self._hostname} 331 {self._clients[client].nick} {command[1]} :No topic is set\r\n".encode())
            elif len(command) == 3:
                self._channels[command[1]].topic = command[2]
                self.sendall(
                    f":{self._clients[client].nick}!{self._clients[client].username}@::1 TOPIC {command[1]} :{command[2]}\r\n")
        else:
            client.send(f"{self._hostname} 442 {self._clients[client].nick} : You're not on that channel\r\n".encode())

    def mode(self, command: list[str], client: socket.socket):
        """
        This function answers the mode request of a client and notifies the client that modes are not supported
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        client.send(f":{self._hostname} 421 {self._clients[client].nick} MODE :Unknown command\r\n".encode())

    # TODO: finish this
    def privmsg(self, command: list[str], client: socket.socket):
        """
        This function sends a message to a channel or a client
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        print(command)
        if ' '.join(command[2:]) == ":":
            client.send(f":{self._hostname} 412 {self._clients[client].nick} :No text to send\r\n".encode())
            return

        if channel_regex.match(command[1]):
            if command[1] in self._channels:
                for _client in self._channels[command[1]].clients:
                    if _client == client:
                        continue
                    _client.send(
                        f":{self._clients[client].nick}!{self._clients[client].username}@::1 PRIVMSG {command[1]} {' '.join(command[2:])}\r\n".encode())
            else:
                client.send(
                    f"{self._hostname} 403 {self._clients[client].nick} {command[1]}: No such channel\r\n".encode())
        elif command[1] in list(map(lambda x: x.nick, self._clients.values())):
            list({k: v for (k, v) in self._clients.items() if command[1] == v.nick}.keys())[0].send(
                f":{self._clients[client].nick}!{self._clients[client].username}@::1 PRIVMSG {command[1]} {' '.join(command[2:])}\r\n".encode())
        else:
            client.send(
                f"{self._hostname} 401 {self._clients[client].nick} {command[1]}: No such nick/channel\r\n".encode())

    def names(self, command: list[str], client: socket.socket):
        """
        This function returns the names of the clients on a channel
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        for client_socket in self._channels[command[1]].clients:
            client.send(
                f":{self._hostname} 353 {self._clients[client].nick} = {command[1]} :{self._clients[client_socket].nick}\r\n".encode())
        client.send(f":{self._hostname} 366 {self._clients[client].nick} {command[1]} :End of NAMES list\r\n".encode())

    def cap(self, command, client):
        """
        This function answers to a cap request and notifies the client that capabilities are not supported
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:

        """
        client.send(f":{self._hostname} 421 {self._clients[client].nick} MODE :Unknown command\r\n".encode())

    def whois(self, command: list[str], client: socket.socket):
        """
        This function answers to a whois request and returns the information of a client
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        if command[1] in list(map(lambda x: x.nick, self._clients.values())):
            client.send(
                f":{self._hostname} 311 {self._clients[client].nick} {command[1]} {self._clients[client].username} ::1 * :{self._clients[client].realname}\r\n".encode())
            client.send(
                f":{self._hostname} 312 {self._clients[client].nick} {command[1]} {self._hostname} :{self._hostname}\r\n".encode())
            client.send(
                f":{self._hostname} 318 {self._clients[client].nick} {command[1]} :End of WHOIS list\r\n".encode())
        else:
            client.send(
                f":{self._hostname} 401 {self._clients[client].nick} {command[1]} :No such nick/channel\r\n".encode())

    def part(self, command: list[str], client: socket.socket):
        """
        This function answers to a part request and removes the client from the channel
        Args:
            command: The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        if command[1] in self._channels:
            if client in self._channels[command[1]].clients:
                self._channels[command[1]].clients.remove(client)
                self._clients[client].channels.remove(command[1])
                self.sendall(
                    f":{self._clients[client].nick}!{self._clients[client].username}@::1 PART {command[1]}\r\n")
            else:
                client.send(
                    f":{self._hostname} 442 {self._clients[client].nick} {command[1]} :You're not on that channel\r\n".encode())
        else:
            client.send(
                f":{self._hostname} 403 {self._clients[client].nick} {command[1]} :No such channel\r\n".encode())

    def handle(self, command: list[str], client: socket.socket):
        """
        This function redirects the command to the correct function
        Args:
            command:The command received from the client
            client: The socket of the client

        Returns:
            None
        """
        command = command.split(" ")
        if command[0] in self.keywords:
            try:
                self.keywords[command[0].upper()](command, client)
            except IndexError:
                client.send(
                    f":{self._hostname} 461 {self._clients[client].nick} {command[0]} :Not enough parameters\r\n".encode())
        else:
            client.send(
                f":{self._hostname} 421 {self._clients[client].nick} {command[0]} :Unknown command\r\n".encode())


@dataclass
class Client(object):
    """
    A class to represent a client

    Attributes:
        nick: The nickname of the client
        username: The username of the client
        real_name: The real name of the client
        channels: A list of channels the client is in

    """
    nick: str = None
    username: str = None
    real_name: str = None
    channels: list = field(default_factory=list)

    def join_channel(self, channel: str):
        self.channels.append(channel)

    def leave_channel(self, channel: str):
        self.channels.remove(channel)


@dataclass
class Channel(object):
    """
    A class to represent a channel

    Attributes:
        clients: A list of clients in the channel
        topic: The topic of the channel
    """
    clients: list = field(default_factory=list)
    topic: str = field(default_factory=str)


if __name__ == "__main__":
    try:
        server = Server()
        server.start()
    except KeyboardInterrupt:
        logging.info("Server stopped")
        sys.exit(0)
    except:
        logging.error("Server stopped unexpectedly")
        sys.exit(1)
