#!/usr/bin/env python
"""cPanel deploy for marketkura.com.

Copies this repo into the live Passenger app folder, installs requirements if they
changed, backs up the database before pending migrations, then migrates, collects
static files and restarts the app.

No secrets live in the repo: environment variables (DB creds, secret key, settings
module) are read at deploy time from cPanel's own "Setup Python App" config.

Never touched on the server: media/, staticfiles/, tmp/, public/, passenger_wsgi.py,
link_static.py, .env, virtualenv.
"""
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = 'marketkura_app'
HOME = Path.home()
APP_DIR = HOME / APP_NAME
REPO_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
SELECTOR_JSON = HOME / '.cl.selector' / 'python-selector.json'
BACKUP_DIR = HOME / 'backups' / 'db'
LOG_FILE = HOME / 'marketkura_deploy.log'

# Top-level names never copied from the repo to the app folder.
SKIP_TOP = {
    '.git', '.claude', '.venv', 'venv', 'media', 'staticfiles', 'tmp', 'public',
    'Claude outputs', '.env', 'db.sqlite3', 'marketkura-deploy.zip', '.cpanel.yml',
    'passenger_wsgi.py', 'link_static.py', '.DS_Store',
}
SKIP_ANYWHERE = {'__pycache__', '.git', '.DS_Store'}


def log(msg):
    line = '[%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG_FILE, 'a') as fh:
        fh.write(line + '\n')


def load_env():
    env = os.environ.copy()
    data = json.loads(SELECTOR_JSON.read_text())
    env.update({k: str(v) for k, v in data[APP_NAME].get('env_vars', {}).items()})
    return env


def copy_tree():
    copied = 0
    for src_root, dirs, files in os.walk(REPO_DIR):
        rel_root = Path(src_root).relative_to(REPO_DIR)
        at_top = rel_root == Path('.')
        dirs[:] = [d for d in dirs
                   if d not in SKIP_ANYWHERE and not (at_top and d in SKIP_TOP)]
        dest_root = APP_DIR / rel_root
        dest_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith(('.pyc', '.pyo')) or name in SKIP_ANYWHERE:
                continue
            if at_top and name in SKIP_TOP:
                continue
            src, dst = Path(src_root) / name, dest_root / name
            if dst.exists() and dst.stat().st_size == src.stat().st_size \
                    and dst.read_bytes() == src.read_bytes():
                continue
            shutil.copy2(src, dst)
            copied += 1
    log('Copied %d changed file(s) into %s' % (copied, APP_DIR))


def run(args, env, check=True):
    log('$ ' + ' '.join(args))
    proc = subprocess.run(args, cwd=str(APP_DIR), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
    out = proc.stdout.strip()
    if out:
        print(out, flush=True)
        with open(LOG_FILE, 'a') as fh:
            fh.write(out + '\n')
    if check and proc.returncode != 0:
        log('FAILED (exit %d). Deploy stopped; app NOT restarted.' % proc.returncode)
        sys.exit(proc.returncode)
    return proc


def install_requirements(env):
    req = APP_DIR / 'requirements.txt'
    stamp = APP_DIR / '.deploy_requirements.sha256'
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text().strip() == digest:
        log('requirements.txt unchanged, skipping pip install')
        return
    run([PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(req)], env)
    stamp.write_text(digest)


def backup_db_if_migrations_pending(env):
    plan = run([PYTHON, 'manage.py', 'showmigrations', '--plan'], env).stdout
    if '[ ]' not in plan:
        log('No pending migrations, skipping DB backup')
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / ('pre-migrate-%s.sql.gz' % time.strftime('%Y%m%d-%H%M%S'))
    pg_env = dict(env, PGPASSWORD=env['DB_PASSWORD'])
    cmd = ['pg_dump', '-h', env.get('DB_HOST', 'localhost'), '-p', env.get('DB_PORT', '5432'),
           '-U', env['DB_USER'], env['DB_NAME']]
    log('Pending migrations found. Backing up database to %s' % target)
    try:
        proc = subprocess.run(cmd, env=pg_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        log('pg_dump not found. Stopping before migrations; take a DB backup manually.')
        sys.exit(2)
    if proc.returncode != 0 or not proc.stdout:
        log('pg_dump failed: %s' % proc.stderr.decode(errors='replace').strip())
        sys.exit(2)
    with gzip.open(target, 'wb') as fh:
        fh.write(proc.stdout)
    for old in sorted(BACKUP_DIR.glob('pre-migrate-*.sql.gz'))[:-5]:
        old.unlink()


def main():
    log('=== Deploy start (repo %s) ===' % REPO_DIR)
    env = load_env()
    copy_tree()
    install_requirements(env)
    backup_db_if_migrations_pending(env)
    run([PYTHON, 'manage.py', 'migrate', '--noinput'], env)
    run([PYTHON, 'manage.py', 'createcachetable'], env)
    run([PYTHON, 'manage.py', 'collectstatic', '--noinput'], env)
    (APP_DIR / 'tmp').mkdir(exist_ok=True)
    (APP_DIR / 'tmp' / 'restart.txt').touch()
    log('=== Deploy done, app restart triggered ===')


if __name__ == '__main__':
    main()
