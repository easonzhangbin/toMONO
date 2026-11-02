"""Show the actual update sheet with a local simulated GitHub release."""
from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[2]
work = Path.home()/'Library/Caches/toMONO/Build15UpdateUIQA'
work.mkdir(parents=True, exist_ok=True)
binary = work/'UpdateViewCheck'
compile_result = subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library',
    '-target', 'arm64-apple-macosx14.0', str(ROOT/'macos/UpdateChecker.swift'),
    str(ROOT/'macos/UpdatesView.swift'), str(ROOT/'macos/tests/UpdateViewCheck.swift'),
    '-o', str(binary), '-framework', 'SwiftUI', '-framework', 'AppKit'],
    capture_output=True, text=True)
(work/'compile.log').write_text(compile_result.stdout+compile_result.stderr)
if compile_result.returncode:
    raise RuntimeError(compile_result.stderr)
run = subprocess.run([str(binary)], env=dict(os.environ,TOMONO_UPDATE_QA_DIR=str(work)),
    capture_output=True,text=True,timeout=40)
(work/'run.log').write_text(run.stdout+run.stderr)
if run.returncode:
    raise RuntimeError(run.stdout+run.stderr)
result = json.loads((work/'update-ui.json').read_text())
print(json.dumps(result,ensure_ascii=False))
assert result['passed'], result
