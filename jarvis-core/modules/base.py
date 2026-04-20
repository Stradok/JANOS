class ModuleBase:
    """
    Minimal base class for modules.
    Each module should implement process(self, input_data) and return JSON-serializable output.
    """
    def __init__(self, name: str):
        self.name = name

    def process(self, input_data):
        raise NotImplementedError("Module must implement process(input_data)")
