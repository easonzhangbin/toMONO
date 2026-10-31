"""Compile the actual recipe/queue value types and run UI-model regressions.

No AppModel is instantiated, no app/resources/worker is launched and no window
is opened. Source slicing isolates value types; it does not rewrite behavior.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
model=ROOT/'macos/ToMONOModel.swift'
lens=ROOT/'macos/LensCorrectionView.swift'
test=ROOT/'macos/tests/DetailModeModelCheck.swift'
types=model.read_text().split('@MainActor final class AppModel:',1)[0]
lens_types=lens.read_text().split('struct LensCaptureInfo {',1)[1].split('\nstruct LensCorrectionSection:',1)[0]
with tempfile.TemporaryDirectory(prefix='tomono-detail-mode-value-check-') as directory:
    folder=Path(directory)
    source=folder/'ActualValueTypes.swift'
    source.write_text(types+'\nstruct LensCaptureInfo {'+lens_types+'\n')
    binary=folder/'DetailModeModelCheck'
    compile_result=subprocess.run(['xcrun','swiftc','-swift-version','5','-parse-as-library',
        '-target','arm64-apple-macosx14.0',str(source),str(test),'-o',str(binary),
        '-framework','SwiftUI','-framework','AppKit','-framework','ImageIO'],
        check=False,capture_output=True,text=True)
    if compile_result.returncode:
        raise RuntimeError(compile_result.stderr)
    result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
    record=json.loads(result.stdout.strip().splitlines()[-1])
    record['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in (model,lens,test)}
    record['scope']='Actual Swift recipe and queue value types only; no app/worker/window. No pixel rendering or UI click claim.'
    record['compiler_stderr']=compile_result.stderr
    out=ROOT/'analysis/evidence/detail_mode_ui_model_check_20261031.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(record,ensure_ascii=False))
