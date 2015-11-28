from NetworkEndpoint import NetworkEndpoint, NetworkPrefixes
import threading
import time
import socket
import errno
from Logger import Log


class TCPEndpoint(NetworkEndpoint):
    def __init__(self, localPort, remotePort, threaded=True, serverSocket=True):
        self.serverSocket = serverSocket
        NetworkEndpoint.__init__(self, localPort, remotePort, threaded)

    def create_socket(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(5)

        if self.serverSocket:
            self.socket.bind(self.localAddr)
            self.socket.listen(2)

        if not self.threaded:
            self.socket.setblocking(0)

    def connect(self):
        try:
            status = 0
            try:
                status = self.socket.connect_ex(self.remoteAddr)
            except socket.error, e:
                Log.error(e)
                self.socket.close()

            if status == errno.EISCONN:
                Log.warn("Already connected!")
                self.peerConnected = True
            elif status == 0:
                Log.info("Connected")
                self.peerConnected = True
            else:
                Log.error(errno.errorcode[status])
                self.peerConnected = False
                return self.peerConnected

            if self.threaded and not self.is_alive():
                self.start()
        except socket.timeout, e:
            print("Timed out")
            self.peerConnected = False
        
        return self.peerConnected