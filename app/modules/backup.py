import logging
import os
import subprocess
import glob
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '..', 'kinder.env'))

PG_HOST = os.getenv('PG_HOST', 'localhost')
PG_PORT = os.getenv('PG_PORT', '5432')
PG_USER = os.getenv('PG_USER', 'postgres')
PG_PASSWORD = os.getenv('PG_PASSWORD', '')

BACKUP_DIR = os.path.join(basedir, '..', 'data', 'backups')
KEEP_DAYS = 15  # number of daily backups to keep per database

DATABASES = ['kinder_web', 'tns_data']

_PG_DUMP_SEARCH_PATHS = [
    '/usr/bin/pg_dump',
    '/usr/local/bin/pg_dump',
    '/opt/homebrew/bin/pg_dump',
]


def _find_pg_dump():
    """Find pg_dump binary, preferring the version that matches the server."""
    import shutil

    # Check Homebrew opt links (keg-only installs), prefer higher versions
    for opt_root in ('/usr/local/opt', '/opt/homebrew/opt'):
        matches = glob.glob(os.path.join(opt_root, 'postgresql*', 'bin', 'pg_dump'))
        if matches:
            return sorted(matches)[-1]  # pick latest

    # Check Homebrew Cellar
    for cellar_root in ('/usr/local/Cellar', '/opt/homebrew/Cellar'):
        matches = glob.glob(os.path.join(cellar_root, 'postgresql*', '*', 'bin', 'pg_dump'))
        if matches:
            return sorted(matches)[-1]

    # Fallback: PATH and well-known system paths
    found = shutil.which('pg_dump')
    if found:
        return found
    for path in _PG_DUMP_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    return None


def run_daily_backup(force=False):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    date_str = datetime.now().strftime('%Y%m%d')

    pg_dump = _find_pg_dump()
    if not pg_dump:
        raise FileNotFoundError('pg_dump not found. Please install PostgreSQL client tools.')

    for db in DATABASES:
        filename = f"{db}_backup_{date_str}.sql"
        filepath = os.path.join(BACKUP_DIR, filename)

        if os.path.exists(filepath) and not force:
            logger.info('%s already exists, skipping.', filename)
            continue

        env = os.environ.copy()
        env['PGPASSWORD'] = PG_PASSWORD

        try:
            result = subprocess.run(
                [
                    pg_dump,
                    '-h', PG_HOST,
                    '-p', PG_PORT,
                    '-U', PG_USER,
                    '-F', 'p',          # plain SQL
                    '-f', filepath,
                    db
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                size = os.path.getsize(filepath)
                logger.info('%s saved (%d KB)', filename, size // 1024)
            else:
                logger.error('ERROR dumping %s: %s', db, result.stderr.strip())
                if os.path.exists(filepath):
                    os.remove(filepath)
        except Exception as e:
            logger.error('Exception dumping %s: %s', db, e)
            if os.path.exists(filepath):
                os.remove(filepath)

    _prune_old_backups()


def _prune_old_backups():
    for db in DATABASES:
        pattern = os.path.join(BACKUP_DIR, f"{db}_backup_*.sql")
        files = sorted(glob.glob(pattern))  # sorted by name = sorted by date
        excess = files[:max(0, len(files) - KEEP_DAYS)]
        for f in excess:
            try:
                os.remove(f)
                logger.info('Pruned old backup: %s', os.path.basename(f))
            except Exception as e:
                logger.error('Failed to prune %s: %s', f, e)
