"""
RunLogger — per-run log writer with DB-change tracking.

Usage in _hourly_run.py / _daily_run.py:

    with RunLogger('hourly') as run_log:
        try:
            ...pipeline...
        finally:
            print_run_summary(...)
            run_log.write_update_table()

Log files:
  logs/daily/daily_YYYY-MM-DD.log        (append mode — one file per day)
  logs/hourly/YYYY-MM-DD/hourly-HH-N.log (write mode — one file per run)
"""

import logging
import sys
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_ROOT = _PROJECT_ROOT / "logs"
_TZ_UTC8 = timezone(timedelta(hours=8))


# ── stdout tee ────────────────────────────────────────────────────────────────

class _TeeWriter:
    """Write simultaneously to the original stdout and a log file."""

    def __init__(self, file_obj, original):
        self._file = file_obj
        self._original = original

    def write(self, text):
        self._original.write(text)
        try:
            self._file.write(text)
        except Exception:
            pass

    def flush(self):
        self._original.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return getattr(self._original, 'isatty', lambda: False)()


# ── RunLogger ─────────────────────────────────────────────────────────────────

class RunLogger:
    """
    Context manager that:
      • tees stdout (all print() calls) to a dated log file
      • captures Python logger output (logger.info/warning/error) to the same file
      • collects per-object DB change events for the update_add table
    """

    _local = threading.local()

    def __init__(self, run_type: str):
        self.run_type = run_type.lower()   # 'daily' or 'hourly'
        self._now = datetime.now(_TZ_UTC8)
        self._log_path: Path | None = None
        self._log_file = None
        self._log_handler: logging.Handler | None = None
        self._original_stdout = None

    # ── log path ──────────────────────────────────────────────────────────────

    def _resolve_log_path(self) -> Path:
        date_str = self._now.strftime("%Y-%m-%d")
        hour_str = self._now.strftime("%H")
        if self.run_type == 'daily':
            log_dir = LOGS_ROOT / "daily"
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir / f"daily_{date_str}.log"
        else:
            log_dir = LOGS_ROOT / "hourly" / date_str
            log_dir.mkdir(parents=True, exist_ok=True)
            existing = list(log_dir.glob(f"hourly-{hour_str}-*.log"))
            run_n = len(existing) + 1
            return log_dir / f"hourly-{hour_str}-{run_n}.log"

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        RunLogger._local.changes = []
        try:
            self._log_path = self._resolve_log_path()
            mode = 'a' if self.run_type == 'daily' else 'w'
            self._log_file = open(self._log_path, mode, encoding='utf-8', buffering=1)

            # Tee stdout → log file
            self._original_stdout = sys.stdout
            sys.stdout = _TeeWriter(self._log_file, sys.stdout)

            # Also capture Python logging to the same file
            self._log_handler = logging.StreamHandler(self._log_file)
            self._log_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            logging.getLogger().addHandler(self._log_handler)

            # Run header
            now_str = self._now.strftime("%Y-%m-%d %H:%M:%S UTC+8")
            now_utc = self._now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            label = self.run_type.upper()
            print(f"\n{'=' * 72}")
            print(f"  {label} RUN  ·  {now_str}  ({now_utc})")
            print(f"{'=' * 72}")
        except Exception as e:
            # Graceful fallback: continue without file logging
            sys.stdout = self._original_stdout or sys.stdout
            print(f"[WARNING] RunLogger: could not open log file: {e}")
            self._log_file = None
            self._log_handler = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            try:
                self._log_handler.close()
            except Exception:
                pass
            self._log_handler = None
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        return False  # never suppress exceptions

    # ── change tracking (thread-local) ────────────────────────────────────────

    @staticmethod
    def record_db_change(obj_name: str, description: str, action: str):
        """
        Record a single DB change event for the update_add table.

        description : left side  — pre-action state, e.g. "Status=Inbox, 1 host found"
        action      : right side — what was done,   e.g. "Status=Follow-up, is_Host=True"
                      Use "No Change" when nothing was written to the DB.
        """
        if not hasattr(RunLogger._local, 'changes'):
            RunLogger._local.changes = []
        RunLogger._local.changes.append({
            'obj_name': obj_name,
            'description': description,
            'action': action,
        })

    @staticmethod
    def _get_changes() -> list[dict]:
        return list(getattr(RunLogger._local, 'changes', []))

    # ── update_add table ──────────────────────────────────────────────────────

    def write_update_table(self):
        """
        Print (and log) the database update_add table.
        Call this after print_run_summary() inside the 'with RunLogger(...)' block.
        """
        changes = self._get_changes()
        if not changes:
            print("\n[INFO] No database status changes recorded this run.")
            return

        SEP  = "=" * 72
        SEP2 = "-" * 72

        changed   = sorted([c for c in changes if c['action'] != 'No Change'],
                            key=lambda c: c['obj_name'])
        no_change = sorted([c for c in changes if c['action'] == 'No Change'],
                            key=lambda c: c['obj_name'])

        name_w = max((len(c['obj_name']) for c in changes), default=12) + 2

        print(f"\n{SEP}")
        print(f"  DATABASE UPDATE TABLE  "
              f"({len(changed)} change(s)  |  {len(no_change)} protected / no-change)")
        print(SEP)

        if changed:
            print(f"  CHANGED ({len(changed)})")
            print(SEP2)
            for c in changed:
                name_col = c['obj_name'].ljust(name_w)
                print(f"    {name_col}  {c['description']}  ->  {c['action']}")

        if changed and no_change:
            print(SEP2)

        if no_change:
            print(f"  NO CHANGE ({len(no_change)})")
            print(SEP2)
            for c in no_change:
                name_col = c['obj_name'].ljust(name_w)
                print(f"    {name_col}  {c['description']}  ->  No Change")

        print(SEP)
