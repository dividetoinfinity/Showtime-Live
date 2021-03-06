import Queue
import select
import socket
import threading
import uuid
from Showtime.zst_node import ZstNode
from Showtime.zst_stage import ZstStage
from ShowtimeBridge.NetworkEndpoint import SimpleMessage, NetworkPrefixes, NetworkEndpoint, NetworkErrors, ReadError
from ShowtimeBridge.UDPEndpoint import UDPEndpoint
from ShowtimeBridge.TCPEndpoint import TCPEndpoint
from ShowtimeBridge.Logger import Log


class RegistrationThread(threading.Thread):
    """Thread dedicated to incoming registration requests so we don't break Showtime req/rep timing"""
    def __init__(self, node):
        threading.Thread.__init__(self)
        self.name = "zst_registrar"
        self.exitFlag = 0
        self.daemon = True
        self.node = node
        self.queued_registrations = Queue.Queue()

    def add_registration_request(self, *args):
        self.queued_registrations.put(args)

    def stop(self):
        self.exitFlag = 1

    def run(self):
        while not self.exitFlag:
            req = self.queued_registrations.get(True)
            self.node.request_register_method(req[0], req[1], req[2], req[3])
        self.join(1)


class LiveRouter(threading.Thread):
    def __init__(self, stageaddress):
        threading.Thread.__init__(self)
        self.name = "LiveRouter"
        Log.set_log_network(True)

        self.exitFlag = 0
        self.daemon = True
        self.serverID = str(uuid.uuid4())[:8]

        if not stageaddress:
            print("Creating internal stage at tcp://127.0.0.1:6000")
            port = 6000
            self.stageNode = ZstStage("ShowtimeStage", port)
            self.stageNode.start()
            stageaddress = "127.0.0.1:" + str(port)

        # Create showtime node
        self.node = ZstNode("LiveNode", stageaddress)
        self.node.start()
        self.node.request_register_node()

        # Create registration thread
        self.registrar = RegistrationThread(self.node)
        self.registrar.daemon = True
        self.registrar.start()

        # Create sockets
        self.tcpEndpoint = TCPEndpoint(6003, 6004, True, True)
        self.udpEndpoint = UDPEndpoint(6001, 6002, True, self.serverID)
        self.tcpEndpoint.add_event_callback(self.event)
        self.udpEndpoint.add_event_callback(self.event)
        self.tcpEndpoint.add_ready_callback(self.endpoint_ready)
        self.udpEndpoint.add_ready_callback(self.endpoint_ready)
        self.inputSockets = {self.tcpEndpoint.socket: self.tcpEndpoint, self.udpEndpoint.socket: self.udpEndpoint}
        self.outputSockets = {}

        self.client = None
        self.clientConnected = False
        self.clientConnectedCallback = None
        self.set_client_connection_status(False)

    def run(self):
        while not self.exitFlag:
            inputready = []
            outputready = []
            exceptready = []

            try:
                inputready, outputready, exceptready = select.select(self.inputSockets.keys(),
                                                                     self.outputSockets.keys(), [], 1)
            except socket.error, e:
                if e[0] == NetworkErrors.EBADF:
                    Log.error("Bad file descriptor! Probably a dead socket passed to select")
                    Log.debug(self.inputSockets.keys())
                    Log.debug(self.outputSockets.keys())

            for s in inputready:
                if s == self.tcpEndpoint.socket:
                    if self.client:
                        Log.error("Live instance already connected. Only one instance can be connected at a time!")
                        return
                    client, address = self.tcpEndpoint.socket.accept()
                    Log.network("New client connecting. Socket is %s" % client)
                    endpoint = TCPEndpoint(-1, -1, True, False, client)
                    endpoint.add_event_callback(self.event)
                    endpoint.add_client_handshake_callback(self.incoming_client_handshake)
                    endpoint.connectionStatus = NetworkEndpoint.PIPE_CONNECTED
                    # endpoint.add_ready_callback(self.endpoint_ready)
                    self.inputSockets[client] = endpoint
                    self.outputSockets[client] = endpoint
                    self.client = endpoint
                    self.set_client_connection_status(True)
                elif s == self.udpEndpoint.socket:
                    try:
                        self.udpEndpoint.recv_msg()
                    except ReadError:
                        pass
                        # Log.network("Read failed. UDP probably closed. %s" % e)
                    except RuntimeError, e:
                        Log.network("Receive failed. Reason: %s" % e)
                else:
                    endpoint = self.inputSockets[s]
                    try:
                        endpoint.recv_msg()
                    except (ReadError, RuntimeError):
                        Log.network("Client socket closed")
                        endpoint.close()
                        self.set_client_connection_status(False)
                        self.client = None
                        try:
                            del self.inputSockets[endpoint.socket]
                            del self.outputSockets[endpoint.socket]
                            try:
                                outputready.remove(endpoint.socket)
                            except ValueError:
                                pass
                        except KeyError:
                            Log.network("Socket missing. In hangup")

            for s in outputready:
                try:
                    endpoint = self.outputSockets[s]
                except KeyError:
                    continue

                try:
                    while 1:
                        msg = endpoint.outgoingMailbox.get_nowait()
                        endpoint.send(msg)
                except Queue.Empty:
                    pass

                if endpoint.enteringImmediate:
                    try:
                        del self.outputSockets[endpoint.socket]
                    except KeyError:
                        pass
                    endpoint.enteringImmediate = False
                    endpoint.immediate = True

            for s in exceptready:
                Log.error("Socket %s in select() except list!. Check for errors." % s)

        self.join(1)

    def endpoint_ready(self, endpoint):
        Log.network("Marking output socket as having queued messages")
        self.outputSockets[endpoint.socket] = endpoint

    def set_client_connection_status(self, status):
        self.clientConnected = status
        if self.clientConnectedCallback:
            self.clientConnectedCallback()

    def incoming_client_handshake(self):
        Log.network("Client sent handshake")
        if self.client:
            self.client.send_handshake_ack()
            self.client.enteringImmediate = True

    def stop(self):
        self.exitFlag = 1

    def close(self):
        self.registrar.stop()
        self.node.close()
        if hasattr(self, "stageNode"):
            self.stageNode.close()
        self.tcpEndpoint.close()
        self.udpEndpoint.close()

    def event(self, event):
        methodname = event.subject[2:]
        msgtype = event.subject[:1]

        if msgtype == NetworkPrefixes.REGISTRATION:
            self.registrar.add_registration_request(methodname, event.msg["methodaccess"], event.msg["args"],
                                                    self.incoming)
        elif msgtype == NetworkPrefixes.OUTGOING or msgtype == NetworkPrefixes.RESPONDER:
            Log.info("Live-->ST: " + str(event.subject) + '=' + str(event.msg))
            if methodname in self.node.methods:
                self.node.update_local_method_by_name(methodname, event.msg)
            else:
                print "Outgoing method not registered!"

    def incoming(self, message):
        Log.info("ST-->Live: " + str(message.name))
        args = message.args if message.args else {}
        self.send_to_live(message.name, args)

    def send_to_live(self, message, args):
        return self.udpEndpoint.send_msg(SimpleMessage(NetworkPrefixes.prefix_incoming(message), args), True)
