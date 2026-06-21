from tools.base import BaseTool


class MathTool(BaseTool):
    name = "math"
    description = "Evaluate a mathematical expression. Params: expression (str)"

    async def execute(self, expression: str = "", **kwargs) -> str:
        try:
            allowed = {"abs", "max", "min", "pow", "round", "sum"}
            namespace = {k: __builtins__[k] for k in allowed if k in __builtins__}
            result = eval(expression, {"__builtins__": {}}, namespace)
            return f"{expression} = {result}"
        except Exception as e:
            return f"Math error: {e}"
