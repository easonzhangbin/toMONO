"""Compile the actual update service and exercise GitHub responses via URLProtocol."""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='tomono-update-check-') as directory:
    binary = Path(directory)/'UpdateCheckerCheck'
    build = subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library',
        '-target', 'arm64-apple-macosx14.0', str(ROOT/'macos/UpdateChecker.swift'),
        str(ROOT/'macos/tests/UpdateCheckerCheck.swift'), '-o', str(binary), '-framework', 'Combine'],
        capture_output=True, text=True)
    if build.returncode:
        raise RuntimeError(build.stderr)
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    if run.returncode:
        raise RuntimeError(run.stdout + run.stderr)
    record = json.loads(run.stdout.strip().splitlines()[-1])
    output = ROOT/'analysis/evidence/update_checker_20261102.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(record, ensure_ascii=False))
