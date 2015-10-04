from __future__ import with_statement

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "ext_libs"))

import encodings

# Import pyro
import Pyro.naming
import Pyro.errors
import Pyro.core
Pyro.config.PYRO_STORAGE = "/tmp"

# Import Live libraries
import Live
from _Framework.ControlSurface import ControlSurface
from _Framework.EncoderElement import EncoderElement

# Import custom live objects
from LiveUtils import *
from ControlSurfaceComponents import *
from ControlSurfaceComponents.PyroEncoderElement import PyroEncoderElement
from LiveSubscriber import LiveSubscriber
from LivePublisher import LivePublisher

from LiveWrappers.PyroWrapper import PyroWrapper
from LiveWrappers.PyroDevice import PyroDevice
from LiveWrappers.PyroDeviceParameter import PyroDeviceParameter
from LiveWrappers.PyroSend import PyroSend
from LiveWrappers.PyroSong import PyroSong
from LiveWrappers.PyroTrack import PyroTrack

from Logger import Log


class ShowtimeBridge(ControlSurface):

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        with self.component_guard():
            self.cInstance = c_instance
            self._suppress_send_midi = True

            Log.set_logger(self.log_message)
            Log.set_log_level(Log.LOG_INFO)
            Log.write("-----------------------")
            Log.write("ShowtimeBridge starting")
            Log.info(sys.version)

            self.initPyroServer()

            # Register methods to the showtimebridge server
            for cls in PyroWrapper.__subclasses__():
                cls.clear_instances()
                cls.register_methods()
                for action in cls.incoming_methods().values():
                    Log.info("Adding %s to incoming callbacks" % action.methodName)
                    self.subscriber.add_incoming_action(action.methodName, cls, action.callback)
                    self.publisher.register_to_showtime(action.methodName, action.methodAccess, action.methodArgs)

                for action in cls.outgoing_methods().values():
                    Log.info("Adding %s to outgoing methods" % action.methodName)
                    self.publisher.register_to_showtime(action.methodName, action.methodAccess)

            # Midi clock to trigger incoming message check
            self.clock = PyroEncoderElement(0, 119)

            # Create the root wrapper
            PyroSong.add_instance(PyroSong(getSong()))

            self.refresh_state()
            self._suppress_send_midi = False

    def initPyroServer(self):
        Pyro.config.PYRO_ES_BLOCKQUEUE = False

        # Event listener
        Pyro.core.initClient()

        # Create publisher and subscriber links to event server
        self.publisher = LivePublisher()
        self.subscriber = LiveSubscriber(self.publisher)

        # Set the global publisher for all wrappers
        PyroWrapper.set_publisher(self.publisher)

    def disconnect(self):
        self._suppress_send_midi = True
        self._suppress_send_midi = False
        ControlSurface.disconnect(self)

    def refresh_state(self):
        ControlSurface.refresh_state(self)
        self.request_rebuild_midi_map()

    def build_midi_map(self, midi_map_handle):
        Log.info("Building midi map...")
        ControlSurface.build_midi_map(self, midi_map_handle)

    def receive_midi(self, midi_bytes):
        # Hack to get a faster update loop. Call our update function each time we receive
        # a midi message
        self.requestLoop()
        ControlSurface.receive_midi(self, midi_bytes)

    def suggest_map_mode(self, cc_no, channel):
        return Live.MidiMap.MapMode.absolute

    def update_display(self):
        #Call the pyro request handler so that messages will always be accepted
        self.requestLoop()
        ControlSurface.update_display(self)

    def requestLoop(self):
        self.subscriber.handle_requests()
