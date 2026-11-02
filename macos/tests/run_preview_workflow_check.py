"""Opt-in real UI/worker QA: --app built.app --work empty_directory RAW RAW RAW.
Copies originals into private fixtures before opening a dedicated QA app.
"""
import argparse,json,os,plistlib,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--app',required=True,type=Path);p.add_argument('--work',required=True,type=Path)
p.add_argument('inputs',nargs=3,type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[2];work=a.work.resolve();work.mkdir(parents=True,exist_ok=False)
inputs=[]
for i,source in enumerate(a.inputs):
    directory=work/f'originals_{i}';directory.mkdir()
    target=directory/source.name;shutil.copyfile(source,target);inputs.append(str(target))
(work/'inputs.json').write_text(json.dumps(inputs))
(work/'WorkspaceView.swift').write_text((root/'macos/WorkspaceView.swift').read_text().split('@main struct ToMONOApp:',1)[0])
app=work/'WorkflowQA.app';contents=app/'Contents';(contents/'MacOS').mkdir(parents=True)
(contents/'Resources').symlink_to(a.app.resolve()/'Contents/Resources')
info={'CFBundleExecutable':'QA','CFBundleIdentifier':'cn.local.tomono.qa.preview11','CFBundleName':'toMONO 1.1 验证','CFBundlePackageType':'APPL','NSHighResolutionCapable':True}
(contents/'Info.plist').write_bytes(plistlib.dumps(info))
sources=[p for p in (root/'macos').glob('*.swift') if p.name!='WorkspaceView.swift']
subprocess.run(['xcrun','swiftc','-swift-version','5','-parse-as-library','-O','-target','arm64-apple-macosx14.0',*map(str,sources),str(work/'WorkspaceView.swift'),str(root/'macos/tests/PreviewWorkflowCheck.swift'),'-o',str(contents/'MacOS/QA'),'-framework','SwiftUI','-framework','AppKit','-framework','ImageIO'],check=True)
subprocess.run([str(contents/'MacOS/QA')],env=dict(os.environ,TOMONO_QA_DIR=str(work)),check=True)
record=json.loads((work/'workflow.json').read_text());print(json.dumps(record,ensure_ascii=False,indent=2))
assert record['passed'],record
