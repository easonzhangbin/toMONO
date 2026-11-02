"""Run the actual RGB-mix alert against queue values; no RAW or worker is used."""
from pathlib import Path
import json
import os
import subprocess

ROOT=Path(__file__).resolve().parents[2]
work=Path.home()/'Library/Caches/toMONO/RGBMixNoticeQA'
work.mkdir(parents=True,exist_ok=True)
workspace=work/'ActualWorkspaceView.swift'
workspace.write_text((ROOT/'macos/WorkspaceView.swift').read_text().split('@main struct ToMONOApp:',1)[0])
sources=sorted(p for p in (ROOT/'macos').glob('*.swift') if p.name!='WorkspaceView.swift')
binary=work/'RGBMixNoticeCheck'
build=subprocess.run(['xcrun','swiftc','-swift-version','5','-parse-as-library','-O',
    '-target','arm64-apple-macosx14.0',*map(str,sources),str(workspace),
    str(ROOT/'macos/tests/RGBMixNoticeCheck.swift'),'-o',str(binary),
    '-framework','SwiftUI','-framework','AppKit','-framework','ImageIO'],capture_output=True,text=True)
(work/'compile.log').write_text(build.stdout+build.stderr)
if build.returncode:raise RuntimeError(build.stderr)
run=subprocess.run([str(binary)],env=dict(os.environ,TOMONO_RGB_QA_DIR=str(work)),
    capture_output=True,text=True,timeout=50)
(work/'run.log').write_text(run.stdout+run.stderr)
if run.returncode:raise RuntimeError(run.stdout+run.stderr)
record=json.loads((work/'rgb-notice-ui.json').read_text())
print(json.dumps(record,ensure_ascii=False))
assert record['passed'],record
