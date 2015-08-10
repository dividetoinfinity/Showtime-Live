from PyroWrapper import *


class PyroSend(PyroWrapper):
    # Message types
    SEND_UPDATED = "send_updated"
    SEND_SET = "send_set"    

    # -------------------
    # Wrapper definitions
    # -------------------
    def create_listeners(self):
        PyroWrapper.create_listeners(self)
        if self.handle():
            self.handle().add_value_listener(self.send_updated)

    def destroy_listeners(self):
        PyroWrapper.destroy_listeners(self)
        if self.handle():
            try:
                self.handle().remove_value_listener(self.send_updated)
            except RuntimeError:
                Log.write("Couldn't remove send listener")

    @classmethod
    def register_methods(cls):
        PyroSend.add_outgoing_method(PyroSend.SEND_UPDATED)
        PyroSend.add_incoming_method(PyroSend.SEND_SET, ["id", "value"], PyroSend.send_set)

    # --------
    # Incoming
    # --------
    @staticmethod
    def send_set(args):
        PyroSend.findById(args["id"]).handle().value = float(args["value"])

    # --------
    # Outgoing
    # --------
    def send_updated(self):
        self.update(PyroSend.SEND_UPDATED, self.handle().value)
