from .base import ModuleBase

class EchoModule(ModuleBase):
    def __init__(self):
        super().__init__("echo")

    def process(self, input_data):
        # input_data is expected to be a dict; return a dict
        return {
            "status": "ok",
            "module": self.name,
            "received": input_data,
            "message": "Echo from Jarvis core"
        }
