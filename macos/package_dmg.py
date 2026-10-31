"""Package a verified local app and its matching documentation without altering prior releases."""
import argparse,hashlib,json,os,plistlib,re,shutil,subprocess,tempfile,uuid
from pathlib import Path

def package(app,output):
    app=app.resolve();output=output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    resources=app/'Contents/Resources';info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    manifest=json.loads((resources/'ReleaseManifest.json').read_text())
    assert manifest['release']==info['ToMONOReleaseLabel']
    for name,digest in manifest['documents'].items():
        assert hashlib.sha256((resources/name).read_bytes()).hexdigest()==digest,'Documentation mismatch: '+name
        source=Path(__file__).parent/'assets'/name
        assert (resources/name).read_bytes()==source.read_bytes(),'Outdated packaged documentation: '+name
    # Keep a release guard for retired identifiers, including native ABI names.
    retired_root=bytes.fromhex('646e67')
    forbidden=re.compile(retired_root+rb'[\s_-]*'+bytes.fromhex('6d6f6e6f6368726f6d65')+b'|'+bytes.fromhex('646e676d'),re.I)
    owned=[app/'Contents/MacOS/toMONO',resources/'HelpContent.json',resources/'ReleaseNotes.txt',
           resources/'ReleaseManifest.json',resources/'ResearchReferences.json',*resources.glob('backend/*.so'),*resources.glob('backend/*.py'),
           *resources.glob('backend/build/**/*.dylib')]
    assert all(not forbidden.search(p.name.encode()) and not forbidden.search(p.read_bytes()) for p in owned),'Unexpected retired identifier in owned application content'
    size=sum(p.stat().st_size for p in app.rglob('*') if p.is_file())
    with tempfile.TemporaryDirectory(prefix='tomono-image-') as temporary:
        work=Path(temporary);rw=work/'working.dmg';mount=work/'mounted';mount.mkdir();ready=work/'ready.dmg'
        def run(args,check=True):
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            if check and result.returncode:raise RuntimeError(' '.join(args)+'\n'+result.stdout)
            return result
        run(['codesign','--verify','--deep','--strict',str(app)])
        run(['hdiutil','create','-size',str(max(220,(size*12//10+2**20-1)//2**20))+'m','-fs','HFS+','-volname','toMONO '+info['ToMONOReleaseLabel'],'-type','UDIF',str(rw)])
        run(['hdiutil','attach','-nobrowse','-mountpoint',str(mount),str(rw)])
        try:
            def copy_file(source,destination):
                shutil.copyfile(source,destination);os.chmod(destination,os.stat(source).st_mode&0o777);return destination
            shutil.copytree(app,mount/'toMONO.app',symlinks=True,copy_function=copy_file)
            (mount/'Applications').symlink_to('/Applications')
            shutil.copyfile(resources/'ReleaseNotes.txt',mount/'本版说明.txt')
            # Remove only build-artifact Finder metadata. Keep quarantine and all
            # security-related attributes intact; they are not an installation fix.
            for key in ('com.apple.FinderInfo','com.apple.ResourceFork'):
                run(['xattr','-r','-d',key,str(mount/'toMONO.app')],check=False)
            run(['codesign','--verify','--deep','--strict',str(mount/'toMONO.app')])
        finally:run(['hdiutil','detach',str(mount)])
        run(['hdiutil','convert',str(rw),'-format','UDZO','-o',str(ready)])
        run(['hdiutil','verify',str(ready)])
        run(['hdiutil','attach','-readonly','-nobrowse','-mountpoint',str(mount),str(ready)])
        try:
            run(['codesign','--verify','--deep','--strict',str(mount/'toMONO.app')])
            assert (mount/'Applications').resolve()==Path('/Applications')
            assert (mount/'toMONO.app/Contents/Resources/ReleaseManifest.json').read_bytes()==(resources/'ReleaseManifest.json').read_bytes()
        finally:run(['hdiutil','detach',str(mount)])
        if output.exists():output.rename(output.with_name(output.stem+'.previous-'+uuid.uuid4().hex[:8]+output.suffix))
        shutil.copyfile(ready,output)
    digest=hashlib.file_digest(output.open('rb'),'sha256').hexdigest()
    output.with_name(output.stem.removesuffix('-AppleSilicon')+'-SHA256SUMS.txt').write_text(digest+'  '+output.name+'\n')
    report={'release':manifest['release'],'dmg':str(output),'bytes':output.stat().st_size,'sha256':digest,
        'image_verified':True,'read_only_mounted_signature_valid':True,'documentation_synced':True,
        'owned_branding_scan_passed':True,'signing':'ad-hoc','notarized':False}
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--report',type=Path)
    args=parser.parse_args();report=package(args.app,args.output)
    if args.report:args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
