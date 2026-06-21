import platform
import shutil

from tools.base import BaseTool


class SystemTool(BaseTool):
    name = "system"
    description = "Get system info. Params: info (str: os|cpu|memory|disk|all)"

    async def execute(self, info: str = "all", **kwargs) -> str:
        lines = []
        if info in ("os", "all"):
            lines.append(f"OS: {platform.system()} {platform.release()}")
            lines.append(f"Host: {platform.node()}")
        if info in ("cpu", "all"):
            lines.append(f"CPU: {platform.processor() or 'N/A'}")
            try:
                import psutil
                lines.append(f"CPU cores: {psutil.cpu_count()}")
                lines.append(f"CPU usage: {psutil.cpu_percent()}%")
            except ImportError:
                lines.append("CPU details: install psutil")
        if info in ("memory", "all"):
            try:
                import psutil
                mem = psutil.virtual_memory()
                lines.append(f"RAM: {mem.total // (1024**3)}GB total, {mem.percent}% used")
            except ImportError:
                lines.append("Memory info: install psutil")
        if info in ("disk", "all"):
            try:
                import psutil
                d = psutil.disk_usage("/")
                lines.append(f"Disk: {d.total // (1024**3)}GB total, {d.percent}% used")
            except ImportError:
                total, _, free = shutil.disk_usage("/")
                lines.append(f"Disk: {total // (1024**3)}GB total, {free // (1024**3)}GB free")
        return "\n".join(lines)
