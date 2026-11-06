"""Cooperative cancellation while copying and checking fixed compiler inputs."""
import os
from pathlib import Path


def check_stop():
    path=os.environ.get('ECRA_JOB_STOP_FILE')
    if path and Path(path).is_file():
        raise KeyboardInterrupt('已安全停止输入固定/校验，原固件及上次有效扫描保留')
