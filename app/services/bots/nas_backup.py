"""NAS backup bot: moves what the reduction pipeline no longer needs from its folder to the lab NAS (SMB), so the
disk does not fill up. The pipeline itself runs under its own account (not from Kinder); this bot only moves:

    RAW_IMG_Sync        nights not from this month or last month (the two months the download step fetches)
    MasterBDF           dated masters older than 30 days whose raw frames are gone already; the undated (global)
                        masters and the newest master of each setup always stay
    Calibrated_Science  target folders whose newest frame is older than 60 days and whose raw frames are gone

"Raw frames gone" matters: raw_selection_copy.py rebuilds a master or a calibrated frame that is missing while its
raw frame is still in RAW_IMG_Sync, so a master or a target only moves once its month has left the download window.
Months are UTC+8. On the NAS every folder keeps the layout it has here, below NAS_PATH; a target folder that moves
again later is merged into the one already there. Each file is copied, checked by size and only then deleted
here, so a run that runs out of time (NAS_ARCHIVE_MINUTES) goes on from there next time. A run is skipped while
the pipeline is working (a pipeline script running, or its folders changed in the last 10 minutes).
The Kinder user needs write access to the three folders (an ACL, see README "NAS backup").
Every move is appended to app/log/bots/nas_backup_moves.jsonl; Admin › Bots › NAS backup › Moves shows the
recent ones and what the next run would move.

The share is used where it is already mounted (Finder), else mounted with mount_smbfs below ~/Library/Kinder/nas
for the run and unmounted afterwards. Only mounts of the Kinder user count: a share another account mounted
cannot be written from here.

Settings (kinder.env):
    NAS_IP, NAS_USER, NAS_PWD   the SMB server and login (unset NAS_IP and NAS_PATH = bot off)
    NAS_ARCHIVE_INTERVAL_MIN    run every this many minutes (default 60)
    NAS_PATH                    share/folder, e.g. great_data/Auto_Backup (or smb://<ip>/great_data/Auto_Backup)
    NAS_ARCHIVE_MINUTES         time budget of one run (default 20)
    NAS_ARCHIVE_DRY_RUN=1       only log what would move

By hand (lists what would move, nothing changes):  uv run python -m app.services.bots.nas_archive --dry-run
"""
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from . import status

BOT = 'nas_backup'
log = status.get_logger(BOT)
MOVES_FILE = status.BOT_LOG_DIR / 'nas_backup_moves.jsonl'
TZ8 = timezone(timedelta(hours=8))
MASTER_DAYS = 30
CALIBRATED_DAYS = 60
FOLDERS = ('RAW_IMG_Sync', 'MasterBDF', 'Calibrated_Science')
FITS = ('.fits', '.fit', '.fts')
MOUNT_BASE = Path.home() / 'Library' / 'Kinder' / 'nas'
PART = '.kinder-part'
# Synology's thumbnail/index folders, copied along with nights rsynced off a Synology: a Synology share refuses
# to create them (ENOENT), so they are deleted here instead of moved
JUNK_DIRS = ('@eaDir',)
_DATE_RE = re.compile(r'(?<!\d)(20\d\d)(0[1-9]|1[0-2])[0-3]\d(?!\d)')
_MJD_RE = re.compile(r'_MJD(\d{5})(?!\d)')
_MJD0 = date(1858, 11, 17)
QUIET_SECS = 600
# what a running pipeline keeps touching (as in reduction.ACTIVITY)
ACTIVITY = ('rsync_script.sh', 'Process_temp', 'Astrometry_temp', 'MasterBDF', 'Calibrated_Science')


# ── settings ──────────────────────────────────────────────────────────────────

def settings():
    """{'ip', 'user', 'pwd', 'share', 'sub'} from kinder.env, or None when the NAS is not set up."""
    ip = (os.environ.get('NAS_IP') or '').strip()
    path = (os.environ.get('NAS_PATH') or '').strip()
    if path.lower().startswith('smb://'):
        host, _, path = path[6:].partition('/')
        ip = ip or host.split('@')[-1]
    parts = [unquote(p) for p in path.split('/') if p]
    if not ip and not parts:
        return None
    return {'ip': ip, 'user': (os.environ.get('NAS_USER') or '').strip(), 'pwd': os.environ.get('NAS_PWD') or '',
            'share': parts[0] if parts else '', 'sub': '/'.join(parts[1:])}


def configured():
    return settings() is not None


def setup_problem():
    s = settings()
    if s is None:
        return 'NAS not set up: set NAS_IP, NAS_USER, NAS_PWD and NAS_PATH in kinder.env.'
    missing = [k for k, v in (('NAS_IP', s['ip']), ('NAS_USER', s['user']), ('NAS_PWD', s['pwd']),
                              ('NAS_PATH', s['share'])) if not v]
    return ('NAS archive: set ' + ', '.join(missing)) if missing else ''


def target_label():
    """Where things go, for the page and the log (never the password)."""
    s = settings()
    return f"smb://{s['ip']}/{s['share']}" + (f"/{s['sub']}" if s['sub'] else '') if s else ''


def dry_run():
    return (os.environ.get('NAS_ARCHIVE_DRY_RUN') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def interval_min():
    try:
        return max(5, int(os.environ.get('NAS_ARCHIVE_INTERVAL_MIN') or 60))
    except ValueError:
        return 60


def budget_secs():
    try:
        return max(1, int(os.environ.get('NAS_ARCHIVE_MINUTES') or 20)) * 60
    except ValueError:
        return 20 * 60


# ── what moves ────────────────────────────────────────────────────────────────

def kept_months(today):
    """The months the download step fetches: this one and the one before, as 'YYYYMM'."""
    prev = today.replace(day=1) - timedelta(days=1)
    return {today.strftime('%Y%m'), prev.strftime('%Y%m')}


def month_of_name(name):
    """'YYYYMM' of the first full date (YYYYMMDD) in a name, e.g. LOT20261031 → 202610; None without one."""
    m = _DATE_RE.search(name)
    return m.group(1) + m.group(2) if m else None


def mjd_date(mjd):
    return _MJD0 + timedelta(days=int(mjd))


def raw_base(root):
    """The folder whose entries are nights: the synced lulin_data folder when it is there, else RAW_IMG_Sync."""
    from .obs_log import raw_dir
    raw = raw_dir()
    return raw if raw and raw.is_dir() else root / 'RAW_IMG_Sync'


def raw_candidates(root, today):
    base = raw_base(root)
    if not base.is_dir():
        return []
    keep = kept_months(today)
    out = []
    for p in sorted(base.iterdir()):
        month = None if p.name.startswith('.') else month_of_name(p.name)
        if month and month not in keep:
            out.append(p)
    return out


def master_candidates(root, today):
    mb = root / 'MasterBDF'
    if not mb.is_dir():
        return []
    keep = kept_months(today)
    groups = {}
    for p in mb.iterdir():
        m = _MJD_RE.search(p.name)
        if m and p.is_file() and p.suffix.lower() in FITS:
            groups.setdefault(p.name[:m.start()] + p.name[m.end():], []).append((int(m.group(1)), p))
    out = []
    for items in groups.values():
        items.sort()
        for mjd, p in items[:-1]:                  # the newest of each setup stays
            d = mjd_date(mjd)
            if (today - d).days > MASTER_DAYS and d.strftime('%Y%m') not in keep:
                out.append(p)
    return sorted(out)


def _newest_frame(folder):
    """Date of the newest frame in a target folder: the MJD in the file names, else the file times."""
    mjds, mtimes = [], []
    for dirpath, _, files in os.walk(folder):
        for f in files:
            if f.startswith('.') or not f.lower().endswith(FITS):
                continue
            m = _MJD_RE.search(f)
            if m:
                mjds.append(int(m.group(1)))
            else:
                try:
                    mtimes.append(os.stat(os.path.join(dirpath, f)).st_mtime)
                except OSError:
                    pass
    if mjds:
        return mjd_date(max(mjds))
    if mtimes:
        return datetime.fromtimestamp(max(mtimes), TZ8).date()
    return None


def calibrated_candidates(root, today):
    cal = root / 'Calibrated_Science'
    if not cal.is_dir():
        return []
    keep = kept_months(today)
    out = []
    for p in sorted(cal.iterdir()):
        if p.name.startswith('.') or not p.is_dir():
            continue
        d = _newest_frame(p)
        if d and (today - d).days > CALIBRATED_DAYS and d.strftime('%Y%m') not in keep:
            out.append(p)
    return out


def plan(root, today=None):
    """[(folder label, local path, path below the NAS folder)] of everything that would move now."""
    today = today or datetime.now(TZ8).date()
    raw_root = root / 'RAW_IMG_Sync'
    out = []
    for p in raw_candidates(root, today):
        try:
            rel = p.relative_to(raw_root)
        except ValueError:                         # OBS_RAW_DIR outside the reduction folder
            rel = Path(p.name)
        out.append(('RAW_IMG_Sync', p, Path('RAW_IMG_Sync') / rel))
    out += [('MasterBDF', p, Path('MasterBDF') / p.name) for p in master_candidates(root, today)]
    out += [('Calibrated_Science', p, Path('Calibrated_Science') / p.name) for p in calibrated_candidates(root, today)]
    return out


# ── moving ────────────────────────────────────────────────────────────────────

def _size(path):
    if path.is_file():
        return path.stat().st_size
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


def _gb(n):
    return f'{n / 1e9:.2f} GB' if n >= 1e8 else f'{n / 1e6:.1f} MB'


def _move_file(src, dest):
    """Copy src to dest (via a .kinder-part file), check the size, then delete src. Returns the bytes moved."""
    size = src.stat().st_size
    if dest.is_file() and dest.stat().st_size == size:    # already there from a run that stopped before deleting
        src.unlink()
        return size
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + PART)
    shutil.copyfile(src, part)                     # no copystat: SMB refuses some of the metadata
    if part.stat().st_size != size:
        part.unlink(missing_ok=True)
        raise OSError(f'size check failed for {dest}')
    try:
        st = src.stat()
        os.utime(part, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    os.replace(part, dest)
    src.unlink()
    return size


def _prune_empty(top):
    """Remove the folders left empty below top, top included."""
    if not top.is_dir():
        return
    for dirpath, _, _ in sorted(os.walk(top), key=lambda w: len(w[0]), reverse=True):
        try:
            names = [n for n in os.listdir(dirpath) if n != '.DS_Store']
            if not names:
                ds = os.path.join(dirpath, '.DS_Store')
                if os.path.exists(ds):
                    os.unlink(ds)
                os.rmdir(dirpath)
        except OSError:
            pass


def move(src, dest, deadline, should_stop):
    """Move a file or a whole folder to dest. Returns (files, bytes, finished)."""
    files = moved = 0
    if src.is_file():
        return 1, _move_file(src, dest), True
    for dirpath, dirnames, names in os.walk(src):
        for junk in [d for d in dirnames if d in JUNK_DIRS]:
            dirnames.remove(junk)
            shutil.rmtree(os.path.join(dirpath, junk), ignore_errors=True)
        dirnames.sort()
        for name in sorted(names):
            if name == '.DS_Store':
                continue
            if time.monotonic() > deadline or should_stop():
                _prune_empty(src)
                return files, moved, False
            f = Path(dirpath) / name
            moved += _move_file(f, dest / f.relative_to(src))
            files += 1
    _prune_empty(src)
    return files, moved, True


# ── the SMB share ─────────────────────────────────────────────────────────────

def find_mount(ip, share):
    """Where //…@ip/share is mounted already by this user (e.g. in Finder), else None."""
    try:
        out = subprocess.run(['/sbin/mount'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    me = getpass.getuser()
    for line in out.splitlines():
        m = re.match(r'//(?:[^@\s]+@)?([^/\s]+)/(\S+) on (.+?) \(((?:smbfs|cifs)[^)]*)\)', line)
        if not m or m.group(1).lower() != ip.lower() or unquote(m.group(2)).lower() != share.lower():
            continue
        by = re.search(r'mounted by ([^,]+)', m.group(4))
        if (by.group(1).strip() if by else me) == me:
            return Path(m.group(3))
    return None


def mount(s):
    """(mount point, mounted_by_us). Raises RuntimeError with mount_smbfs's reason (password hidden)."""
    found = find_mount(s['ip'], s['share'])
    if found:
        return found, False
    mp = MOUNT_BASE / s['share']
    mp.mkdir(parents=True, exist_ok=True)
    url = f"//{quote(s['user'], safe='')}:{quote(s['pwd'], safe='')}@{s['ip']}/{quote(s['share'])}"
    try:
        r = subprocess.run(['/sbin/mount_smbfs', '-N', url, str(mp)], capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Mounting smb://{s['ip']}/{s['share']} timed out (is the NAS reachable?)")
    if r.returncode != 0:
        why = (r.stderr or r.stdout or f'exit {r.returncode}').strip()
        for secret in {s['pwd'], quote(s['pwd'], safe='')} - {''}:
            why = why.replace(secret, '***')
        raise RuntimeError(f"Mounting smb://{s['ip']}/{s['share']} failed: {why}")
    return mp, True


def unmount(mp):
    for cmd in (['/sbin/umount', str(mp)], ['/usr/sbin/diskutil', 'unmount', str(mp)]):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass


# ── the step ──────────────────────────────────────────────────────────────────

def step(root, on_line, should_stop=lambda: False, today=None):
    """One archive pass. Logs through on_line; returns the exit code (0 ok, 1 something failed)."""
    root = Path(root)
    s = settings()
    problem = setup_problem()
    if problem:
        on_line(problem)
        return 1
    todo = plan(root, today)
    if not todo:
        on_line('Nothing to move to the NAS.')
        return 0
    counts = {}
    for label, _, _ in todo:
        counts[label] = counts.get(label, 0) + 1
    on_line('To move: ' + ', '.join(f'{n} from {k}' for k, n in counts.items()) + f' → {target_label()}')
    if dry_run():
        for label, src, rel in todo:
            on_line(f'would move {src.relative_to(root) if src.is_relative_to(root) else src} → {rel} ({_gb(_size(src))})')
        on_line('Dry run (NAS_ARCHIVE_DRY_RUN): nothing moved.')
        return 0
    try:
        mp, ours = mount(s)
    except RuntimeError as e:
        on_line(str(e))
        return 1
    errors = 0
    total_files = total_bytes = 0
    try:
        dest_root = mp / s['sub'] if s['sub'] else mp
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            on_line(f'No access to {dest_root}: {e}. If macOS blocks it, give '
                    f'{os.path.realpath(sys.executable)} Full Disk Access (System Settings › Privacy & Security).')
            return 1
        deadline = time.monotonic() + budget_secs()
        for label, src, rel in todo:
            if time.monotonic() > deadline or should_stop():
                on_line('Time budget used up (NAS_ARCHIVE_MINUTES); the rest moves next run.'
                        if not should_stop() else 'Stopped; the rest moves next run.')
                break
            if not (os.access(src.parent, os.W_OK) and (src.is_file() or os.access(src, os.W_OK))):
                errors += 1
                on_line(f'FAILED {rel}: {getpass.getuser()} may not delete it here (needs the ACL, see README "NAS backup")')
                continue
            try:
                files, size, finished = move(src, dest_root / rel, deadline, should_stop)
            except OSError as e:
                errors += 1
                on_line(f'FAILED {rel}: {e}')
                continue
            total_files += files
            total_bytes += size
            _record(label, rel, files, size, finished)
            on_line(f"moved {rel} ({files} file{'s' if files != 1 else ''}, {_gb(size)})"
                    + ('' if finished else ' — not finished, goes on next run'))
            if not finished:
                break
    finally:
        if ours:
            unmount(mp)
    on_line(f'NAS archive: {total_files} files, {_gb(total_bytes)} moved' + (f', {errors} failed' if errors else ''))
    return 1 if errors else 0


# ── history and the page ──────────────────────────────────────────────────────

def _record(folder, rel, files, size, finished):
    row = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'folder': folder, 'path': str(rel),
           'files': files, 'bytes': size, 'finished': finished}
    try:
        MOVES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MOVES_FILE, 'a') as fh:
            fh.write(json.dumps(row) + '\n')
    except OSError:
        log.warning('Could not write %s', MOVES_FILE)


def recent_moves(limit=200):
    """The latest moves, newest first (limit=None: all of them)."""
    try:
        with open(MOVES_FILE) as fh:
            lines = fh.readlines()
            if limit:
                lines = lines[-limit:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


_overview_cache = {'at': 0.0, 'value': None}


def overview(max_age=300):
    """For the Moves tab: where to, the recent moves with totals, and what the next run would move."""
    now = time.monotonic()
    if _overview_cache['value'] is not None and now - _overview_cache['at'] < max_age:
        return _overview_cache['value']
    from .reduction import root as reduction_root
    r = reduction_root()
    moves = recent_moves(limit=None)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    month = [m for m in moves if m.get('at', '') >= since]     # all of them: a first run moves thousands
    out = {'target': target_label(), 'problem': setup_problem(), 'root': str(r or ''), 'interval_min': interval_min(),
           'budget_min': budget_secs() // 60, 'dry_run': dry_run(), 'moves': moves[:100],
           'month': {'items': len(month), 'files': sum(m.get('files', 0) for m in month),
                     'bytes': sum(m.get('bytes', 0) for m in month)},
           'pending': [], 'pending_counts': {}, 'pending_bytes': 0, 'busy': ''}
    if r and r.is_dir():
        out['busy'] = pipeline_busy(r)
        todo = plan(r)
        for label, src, rel in todo:
            out['pending_counts'][label] = out['pending_counts'].get(label, 0) + 1
        for label, src, rel in todo[:100]:
            try:
                size = _size(src)
            except OSError:
                size = None
            out['pending'].append({'folder': label, 'path': str(rel), 'bytes': size})
            out['pending_bytes'] += size or 0
    _overview_cache.update(at=time.monotonic(), value=out)
    return out


# ── the bot ───────────────────────────────────────────────────────────────────

def pipeline_busy(root):
    """Why the pipeline looks busy right now ('' when it is quiet)."""
    from . import reduction
    ext = reduction.external_runs()
    if ext:
        return f"{ext[0]['script']} is running (pid {ext[0]['pid']})"
    now = time.time()
    for name in ACTIVITY:
        try:
            age = now - (root / name).stat().st_mtime
        except OSError:
            continue
        if age < QUIET_SECS:
            return f'{name} changed {int(age // 60)} min ago'
    return ''


def _run():
    from .reduction import root as reduction_root
    if not configured():
        raise RuntimeError('NAS not set up (NAS_IP / NAS_PATH in kinder.env).')
    problem = setup_problem()
    if problem:
        raise RuntimeError(problem)
    r = reduction_root()
    if not r or not r.is_dir():
        raise RuntimeError(f'Reduction folder not found: {r or "(not set)"} — set REDUCTION_PIPELINE_DIR.')
    busy = pipeline_busy(r)
    if busy:
        log.info('Pipeline busy (%s); trying again next run.', busy)
        return f'Skipped: pipeline busy ({busy}).'
    lines = []

    def on_line(line):
        log.info('%s', line)
        lines.append(line)
    rc = step(r, on_line)
    summary = lines[-1] if lines else 'Done.'
    if rc:
        status.event(BOT, summary, level='error')
        raise RuntimeError(summary)
    if 'moved' in summary and not summary.startswith('NAS archive: 0 files'):
        status.event(BOT, summary)
    return summary


def run():
    return status.guarded_run(BOT, _run)


if __name__ == '__main__':
    import argparse

    from app import config  # noqa: F401  (loads kinder.env)
    from app.services.bots.reduction import root as reduction_root

    ap = argparse.ArgumentParser(description='Move old reduction data to the NAS (see the module docstring).')
    ap.add_argument('--dry-run', action='store_true', help='only list what would move')
    a = ap.parse_args()
    if a.dry_run:
        os.environ['NAS_ARCHIVE_DRY_RUN'] = '1'
    r = reduction_root()
    if not r or not r.is_dir():
        sys.exit(f'Reduction folder not found: {r or "(not set)"} — set REDUCTION_PIPELINE_DIR.')
    sys.exit(step(r, print))
