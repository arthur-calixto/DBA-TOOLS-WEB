"""Prova que os testes detectam os seis bloqueios, sem editar o working tree."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {
    'entry_count': ('test_no_entry_count_ceiling', 'len(archive.infolist()) > settings.zip_max_entries'),
    'decompressed_size': ('test_no_decompressed_size_ceiling', 'sum(e.file_size for e in archive.infolist()) > settings.monitor_max_uncompressed_bytes'),
    'compression_ratio': ('test_no_compression_ratio_ceiling', 'any(e.file_size > max(1, e.compress_size) * settings.zip_max_ratio for e in archive.infolist())'),
    'log_size': ('test_no_log_size_ceiling', 'any(e.file_size > settings.monitor_max_log_bytes for e in archive.infolist() if e.filename == "Monitor_Consulta.log")'),
}


def main():
    with TemporaryDirectory(prefix='monitor-mutations-') as temporary:
        target = Path(temporary)
        for directory in ('app', 'tests'):
            shutil.copytree(ROOT / directory, target / directory, ignore=shutil.ignore_patterns('__pycache__'))
        source = target / 'app/monitor/streaming.py'
        original = source.read_text()
        variants = {}
        for name, (test, condition) in MUTATIONS.items():
            mutant = original.replace('    with zipfile.ZipFile(file) as archive:',
                '    from app.config import settings\n    with zipfile.ZipFile(file) as archive:\n'
                f'        if {condition}:\n            raise ValueError("Reintroduced limit")')
            variants[name] = (test, mutant)
        variants['record_count'] = ('test_no_record_count_ceiling', original.replace(
            '                        count += 1',
            '                        count += 1\n                        from app.config import settings\n                        if count > settings.monitor_max_records:\n                            raise ValueError("Reintroduced record limit")'))
        variants['deadline'] = ('test_no_processing_deadline', original.replace(
            'def analyze_archive(file):',
            'def analyze_archive(file):\n    from time import monotonic\n    from app.config import settings\n    from app.monitor.limits import check_deadline\n    check_deadline(monotonic() + settings.monitor_processing_seconds)'))
        environment = dict(os.environ, PYTHONPATH=str(target / 'tests'), PYTHONDONTWRITEBYTECODE='1')
        for name, (test, mutant) in variants.items():
            source.write_text(original)
            command = [sys.executable, '-m', 'unittest', f'test_monitor_streaming.StreamingMonitorTests.{test}', '-v']
            baseline = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, timeout=60)
            if baseline.returncode:
                raise RuntimeError(f'Baseline failed for {name}: {baseline.stderr}')
            source.write_text(mutant)
            result = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, timeout=60)
            if result.returncode != 1 or 'AssertionError' not in result.stderr:
                raise RuntimeError(f'Mutation not detected: {name}\n{result.stderr}')
            print(f'{name}: baseline PASS; reintroduced limit FAIL (detected)', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
