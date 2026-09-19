"""Bounded native commands with persistent logs and process-group cleanup."""

from dataclasses import asdict, dataclass
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
import time


class ToolExecutionError(RuntimeError):
    """A native tool failed before it could return a domain-level result."""

    def __init__(self, message: str, *, status: str = "tool_error") -> None:
        if status not in {"tool_error", "timeout"}:
            raise ValueError(f"unsupported tool failure status: {status}")
        super().__init__(message)
        self.status = status


class EvidenceMismatchError(ValueError):
    """Saved or replayed evidence disagrees with the expected execution."""

    def __init__(self, message: str, *, status: str = "state_mismatch") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    log_path: str
    stderr_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def run_command(command: list[str], *, cwd: Path, log_path: Path,
                timeout: float, env: dict[str, str] | None = None,
                stderr_path: Path | None = None) -> CommandResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    timed_out = False
    with ExitStack() as files:
        output = files.enter_context(log_path.open("w"))
        if stderr_path:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
        errors = files.enter_context(stderr_path.open("w")) if stderr_path else subprocess.STDOUT
        try:
            child = subprocess.Popen(command, cwd=cwd, stdout=output,
                                     stderr=errors, env=env,
                                     start_new_session=True)
        except OSError as error:
            output.write(str(error))
            return CommandResult(command, 127, time.monotonic() - start, False, str(log_path))
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Child tools can spawn solvers: kill the group, not just the launcher.
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            except ProcessLookupError:
                pass
            # A launcher can exit while one of its descendants ignores SIGTERM.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
    return CommandResult(command, child.returncode, time.monotonic() - start,
                         timed_out, str(log_path), str(stderr_path) if stderr_path else None)
