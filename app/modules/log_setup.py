"""
Daily rotating file logger for the Kinder web application.
Writes to app/log/YYYY-MM-DD.log, retains last 7 days.
Redirects sys.stdout so all print() calls are captured.
"""
import io
import logging
import os
import sys
import threading
from datetime import date

_log_dir: str = None


def get_log_dir() -> str:
    return _log_dir


class DailyFileHandler(logging.Handler):
    """Writes log records to {log_dir}/{YYYY-MM-DD}.log, rotates at midnight."""

    def __init__(self, log_dir: str, backup_count: int = 7):
        super().__init__()
        self.log_dir = log_dir
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self._current_date = ''
        self._file = None
        os.makedirs(log_dir, exist_ok=True)

    def _rotate_if_needed(self):
        today = date.today().isoformat()
        if today == self._current_date:
            return
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
        self._file = open(os.path.join(self.log_dir, f'{today}.log'), 'a', encoding='utf-8')
        self._current_date = today
        self._cleanup()

    def _cleanup(self):
        try:
            files = sorted(
                f for f in os.listdir(self.log_dir)
                if f.endswith('.log') and len(f) == 14  # YYYY-MM-DD.log
            )
            while len(files) > self.backup_count:
                os.remove(os.path.join(self.log_dir, files.pop(0)))
        except Exception:
            pass

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lock:
                self._rotate_if_needed()
                self._file.write(msg + '\n')
                self._file.flush()
        except Exception:
            self.handleError(record)

    def handleError(self, record):
        # Write to real stderr to break any recursion chain
        try:
            sys.__stderr__.write(f'[LoggingError] {record}\n')
        except Exception:
            pass

    def close(self):
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
        super().close()


class _StreamToLogger:
    """Redirect sys.stdout / sys.stderr writes through logging."""

    def __init__(self, logger: logging.Logger, level: int):
        self._logger = logger
        self._level = level
        self._buf = ''

    def write(self, msg: str):
        self._buf += msg
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            stripped = line.rstrip()
            if stripped:
                self._logger.log(self._level, stripped)

    def flush(self):
        if self._buf.strip():
            self._logger.log(self._level, self._buf.rstrip())
            self._buf = ''

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation('fileno')


def setup_logging(log_dir: str) -> None:
    """Configure root logger and redirect stdout to the daily log file."""
    global _log_dir
    _log_dir = log_dir

    handler = DailyFileHandler(log_dir, backup_count=7)
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers on reload (Werkzeug reloader starts the process twice)
    root.handlers = [h for h in root.handlers if not isinstance(h, DailyFileHandler)]
    root.addHandler(handler)

    # Silence very noisy third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    logging.captureWarnings(True)

    # Redirect stdout so all print() calls go to the log file
    if not isinstance(sys.stdout, _StreamToLogger):
        sys.stdout = _StreamToLogger(logging.getLogger('app'), logging.INFO)

    logging.getLogger(__name__).info('Logging initialized → %s', log_dir)
