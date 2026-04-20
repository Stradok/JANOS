from .base import ModuleBase

class MathModule(ModuleBase):
    def __init__(self):
        super().__init__("math")

    def process(self, input_data):
        try:
            a = input_data.get("a")
            b = input_data.get("b")
            op = input_data.get("op", "add")

            if op == "add":
                result = a + b
            elif op == "sub":
                result = a - b
            elif op == "mul":
                result = a * b
            elif op == "div":
                if b == 0:
                    return {"error": "Division by zero"}
                result = a / b
            else:
                return {"error": f"Unknown operation: {op}"}

            return {
                "status": "ok",
                "operation": op,
                "a": a,
                "b": b,
                "result": result
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
