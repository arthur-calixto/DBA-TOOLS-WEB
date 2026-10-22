"""Servidor e banco descartáveis para o teste Chromium; nunca utiliza HML.

Requer Playwright e axe-core em NODE_PATH (ver docs/connections.md).
"""
import argparse
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from test_connections import ConnectionsTests  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--visual', action='store_true', help='Validação TER-11 das telas principais')
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    ConnectionsTests.setUpClass()
    fixture = ConnectionsTests('test_complete_creation_listing_reload_edit_archive_and_environment_reuse')
    fixture.setUp()
    settings.public_base_url = 'http://127.0.0.1:18765'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=18765, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Servidor de teste local não iniciou')
            time.sleep(.05)
        from synthetic import archive
        zip_path = Path(fixture.directory.name) / 'monitor-synthetic.zip'
        zip_path.write_bytes(archive())
        script = 'visual.cjs' if args.visual else 'connections.cjs'
        subprocess.run(['node', str(ROOT / 'tests/browser' / script)], cwd=ROOT, check=True,
                       env={**os.environ, 'TER11_MONITOR_ZIP': str(zip_path)})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        fixture.doCleanups()


if __name__ == '__main__':
    main()
