"""Opt-in real loupe/UI/worker check; builds a plain QA executable, no app bundle.

Requires an existing private runtime app, live source/native backends, and an
unlocked macOS session for view creation. Test RAWs are copied; no export occurs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime-app', type=Path, required=True)
parser.add_argument('--work', type=Path, required=True, help='New private QA directory')
parser.add_argument('inputs', type=Path, nargs=2)
args = parser.parse_args()
work = args.work.resolve()
work.mkdir(parents=True, exist_ok=False)
runtime = args.runtime_app.resolve() / 'Contents/Resources'
resources = work / 'QAResources'
resources.mkdir()
for item in runtime.iterdir():
    if item.name != 'backend':
        (resources/item.name).symlink_to(item)
(resources/'backend').symlink_to(ROOT/'portable')
before = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.inputs}
inputs = []
for i, source in enumerate(args.inputs):
    folder = work/f'input_{i}'
    folder.mkdir()
    target = folder/source.name
    shutil.copyfile(source, target)
    inputs.append(str(target))
(work/'inputs.json').write_text(json.dumps(inputs))
workspace = work/'ActualWorkspaceView.swift'
workspace.write_text((ROOT/'macos/WorkspaceView.swift').read_text().split('@main struct ToMONOApp:', 1)[0])
sources = sorted(p for p in (ROOT/'macos').glob('*.swift') if p.name != 'WorkspaceView.swift')
binary = work/'InspectionLoupeCheck'
command = ['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library', '-O',
           '-target', 'arm64-apple-macosx14.0', *map(str, sources), str(workspace),
           str(ROOT/'macos/tests/InspectionLoupeCheck.swift'), '-o', str(binary),
           '-framework', 'SwiftUI', '-framework', 'AppKit', '-framework', 'ImageIO']
compile_result = subprocess.run(command, text=True, capture_output=True)
(work/'compile.log').write_text(compile_result.stdout+compile_result.stderr)
if compile_result.returncode:
    raise RuntimeError(compile_result.stderr)
environment = dict(os.environ, TOMONO_QA_DIR=str(work), TOMONO_QA_RESOURCES=str(resources))
run_result = subprocess.run([str(binary)], env=environment, text=True, capture_output=True, timeout=300)
(work/'run.log').write_text(run_result.stdout+run_result.stderr)
if run_result.returncode:
    raise RuntimeError(run_result.stderr)
result = json.loads((work/'inspection_loupe.json').read_text())
result['source_raw_hashes_unchanged'] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())
result['original_source_sha256'] = before
(work/'inspection_loupe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
assert result['passed'], result
assert result['source_raw_hashes_unchanged'], result
