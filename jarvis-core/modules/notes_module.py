import json
import os
from .base import ModuleBase

class NotesModule(ModuleBase):
    def __init__(self):
        super().__init__("notes")
        self.file_path = "memory/notes.json"
        os.makedirs("memory", exist_ok=True)
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump([], f)

    def _read_notes(self):
        with open(self.file_path, "r") as f:
            return json.load(f)

    def _write_notes(self, notes):
        with open(self.file_path, "w") as f:
            json.dump(notes, f, indent=2)

    def process(self, input_data):
        action = input_data.get("action", "list")

        if action == "add":
            text = input_data.get("text")
            speaker = input_data.get("speaker", "Unknown")  # 👈 default speaker
            if not text:
                return {"error": "Missing note text"}

            notes = self._read_notes()
            notes.append({"speaker": speaker, "note": text})
            self._write_notes(notes)
            return {"status": "ok", "message": f"Note added for {speaker}: {text}"}

        elif action == "list":
            notes = self._read_notes()
            return {"status": "ok", "notes": notes}

        elif action == "delete":
            index = input_data.get("index")
            notes = self._read_notes()
            if index is not None and 0 <= index < len(notes):
                removed = notes.pop(index)
                self._write_notes(notes)
                return {"status": "ok", "message": f"Deleted note: {removed}"}
            return {"error": "Invalid note index"}

        else:
            return {"error": f"Unknown action: {action}"}
