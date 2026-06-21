"""Background hardware monitor for VRAM, RAM, CPU.

Runs as an asyncio background task, polls nvidia-smi + psutil.
Exposes current_load() for the model router to throttle decisions.
"""

import asyncio
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HardwareLoad:
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    cpu_percent: float = 0.0
    gpu_available: bool = False
    gpu_count: int = 0
    vram_percent: float = 0.0
    ram_percent: float = 0.0

    def is_overloaded(self) -> bool:
        """True if system is too loaded for heavy models."""
        return self.vram_percent > 85 or self.ram_percent > 85

    def can_run_model(self, estimated_vram_gb: float = 4.0) -> bool:
        """Check if we can safely load another model."""
        vram_free = self.vram_total_gb - self.vram_used_gb
        ram_free = self.ram_total_gb - self.ram_used_gb
        if self.gpu_available:
            return vram_free > estimated_vram_gb + 1.0
        return ram_free > estimated_vram_gb + 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "vram_used_gb": round(self.vram_used_gb, 1),
            "vram_total_gb": round(self.vram_total_gb, 1),
            "vram_percent": round(self.vram_percent, 1),
            "ram_used_gb": round(self.ram_used_gb, 1),
            "ram_total_gb": round(self.ram_total_gb, 1),
            "ram_percent": round(self.ram_percent, 1),
            "cpu_percent": round(self.cpu_percent, 1),
            "gpu_available": self.gpu_available,
            "gpu_count": self.gpu_count,
            "overloaded": self.is_overloaded(),
        }


def _parse_nvidia_smi() -> tuple[float, float, int]:
    """Parse nvidia-smi output for VRAM used, VRAM total, GPU count.

    Returns (vram_used_gb, vram_total_gb, gpu_count).
    """
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return 0.0, 0.0, 0

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return 0.0, 0.0, 0

        lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        total_vram_used = 0.0
        total_vram_total = 0.0
        gpu_count = 0

        for line in lines:
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    used = float(parts[0].strip())
                    total = float(parts[1].strip())
                    total_vram_used += used
                    total_vram_total += total
                    gpu_count += 1
                except ValueError:
                    continue

        return total_vram_used / 1024.0, total_vram_total / 1024.0, gpu_count
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0.0, 0.0, 0


def _parse_psutil() -> tuple[float, float, float]:
    """Parse psutil for RAM used, RAM total, CPU percent."""
    import psutil

    mem = psutil.virtual_memory()
    return mem.used / (1024**3), mem.total / (1024**3), psutil.cpu_percent(interval=0.1)


class HardwareMonitor:
    """Background hardware monitor. Polls every N seconds.

    Start with: await monitor.start()
    Query with: monitor.current_load
    """

    def __init__(self, poll_interval: float = 5.0):
        self.poll_interval = poll_interval
        self.current_load = HardwareLoad()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        try:
            self.current_load = await self._sample()
        except Exception:
            pass
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _poll_loop(self):
        while self._running:
            await asyncio.sleep(self.poll_interval)
            try:
                self.current_load = await self._sample()
            except Exception:
                pass

    async def _sample(self) -> HardwareLoad:
        load = HardwareLoad()

        vram_used, vram_total, gpu_count = await asyncio.to_thread(_parse_nvidia_smi)
        load.vram_used_gb = vram_used
        load.vram_total_gb = vram_total
        load.gpu_available = gpu_count > 0
        load.gpu_count = gpu_count
        if vram_total > 0:
            load.vram_percent = (vram_used / vram_total) * 100.0

        ram_used, ram_total, cpu = await asyncio.to_thread(_parse_psutil)
        load.ram_used_gb = ram_used
        load.ram_total_gb = ram_total
        load.cpu_percent = cpu
        if ram_total > 0:
            load.ram_percent = (ram_used / ram_total) * 100.0

        return load
