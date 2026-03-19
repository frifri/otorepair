import asyncio
import os
import signal


class ProcessRunner:
    def __init__(self, command: str) -> None:
        self._command = command
        self._process: asyncio.subprocess.Process | None = None
        self._env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    async def start(self) -> asyncio.subprocess.Process:
        self._process = await asyncio.create_subprocess_shell(
            self._command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            preexec_fn=os.setsid,
        )
        return self._process

    async def restart(self) -> asyncio.subprocess.Process:
        await self.stop()
        return await self.start()

    async def stop(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return

        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            await self._process.wait()

    def force_kill(self) -> None:
        """Synchronous, immediate kill — for use in signal handlers."""
        if self._process is None or self._process.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process else None
