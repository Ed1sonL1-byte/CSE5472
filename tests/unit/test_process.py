import os
import sys
import time

from seedbridge.process import run_command


def test_timeout_kills_the_child_process_group(tmp_path):
    pidfile = tmp_path / "child.pid"
    stubborn = "import signal,time;signal.signal(signal.SIGTERM, signal.SIG_IGN);time.sleep(60)"
    script = ("import subprocess,time,pathlib; "
              f"p=subprocess.Popen([{sys.executable!r},'-c',{stubborn!r}]); "
              f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); "
              "time.sleep(60)")
    result = run_command([sys.executable, "-c", script], cwd=tmp_path,
                         log_path=tmp_path / "process.log", timeout=0.5)
    assert result.timed_out
    assert result.resource_usage_status == "unavailable"
    assert "process-tree" in result.resource_usage_reason
    assert pidfile.exists()
    # A terminated child may briefly be a zombie before init reaps it.
    import psutil
    pid = int(pidfile.read_text())
    for _ in range(20):
        if not psutil.pid_exists(pid):
            break
        if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Child process survived process-group timeout")
