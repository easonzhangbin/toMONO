"""Build a local arm64 app with a private Python runtime and metadata tools."""
import os,plistlib,shutil,subprocess,sys,uuid,argparse,hashlib,json
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--release',action='store_true',help='编译自研Python模块并去除调试符号');parser.add_argument('--output',type=Path,help='独立输出应用路径');args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1];PORT=ROOT/'portable';DIST=ROOT/'dist';DIST.mkdir(exist_ok=True)
app=args.output.resolve() if args.output else DIST/'toMONO.app';app.parent.mkdir(parents=True,exist_ok=True);stage=app.parent/('.app-build-'+uuid.uuid4().hex);contents=stage/'Contents';resources=contents/'Resources';(contents/'MacOS').mkdir(parents=True);resources.mkdir()
try:
    subprocess.run(['sh',str(PORT/'build_mac.sh')],check=True)
    sources=[str(p) for p in sorted((ROOT/'macos').glob('*.swift'))]
    subprocess.run(['xcrun','swiftc','-swift-version','5','-parse-as-library','-O','-target','arm64-apple-macosx14.0',*sources,'-o',str(contents/'MacOS/toMONO'),'-framework','SwiftUI','-framework','AppKit','-framework','ImageIO'],check=True)
    # Package the supplied artwork unchanged, apart from standard icon sizes.
    iconset=stage/'toMONO.iconset';iconset.mkdir()
    for size in (16,32,128,256,512):
        for scale in (1,2):
            name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
            subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(ROOT/'macos/assets/AppIcon.png'),'--out',str(iconset/name)],check=True,capture_output=True)
    subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(resources/'toMONO.icns')],check=True)
    shutil.rmtree(iconset)
    info={'CFBundleExecutable':'toMONO','CFBundleIdentifier':'cn.local.tomono.mac',
        'CFBundleName':'toMONO','CFBundleDisplayName':'toMONO','CFBundlePackageType':'APPL','CFBundleIconFile':'toMONO.icns',
        'CFBundleShortVersionString':'1.2.0','CFBundleVersion':'16','ToMONOReleaseLabel':'1.2 正式版','LSMinimumSystemVersion':'14.0',
        'LSApplicationCategoryType':'public.app-category.photography',
        'CFBundleDevelopmentRegion':'zh_CN','CFBundleLocalizations':['zh-Hans'],
        'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','CFBundleDocumentTypes':[{'CFBundleTypeName':'相机RAW文件','CFBundleTypeRole':'Viewer','LSHandlerRank':'Alternate','LSItemContentTypes':['public.camera-raw-image']}]}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    for name in ('HelpContent.json','PrivacyInfo.xcprivacy','ReleaseNotes.txt','ResearchReferences.json'):
        shutil.copy2(ROOT/'macos/assets'/name,resources/name)
    shutil.copyfile(ROOT/'macos/assets/SupportAlipay.jpg',resources/'SupportAlipay.jpg')
    shutil.copyfile(ROOT/'LICENSE',resources/'toMONO-LICENSE.txt')
    (resources/'ReleaseManifest.json').write_text(json.dumps({
        'release':info['ToMONOReleaseLabel'],'version':info['CFBundleShortVersionString'],'build':info['CFBundleVersion'],
        'appearance_reference':'toMONO preview','verified_renderer':'Camera Raw 18.7 (prior appearance validation; no new decoder equality claim)',
        'detail_modes':{'default':'directional','spectral':'C01','spectral_guard':'D11','directional':'D10','lmmse':'IPOL Zhang-Wu v1.1 (ordinary Bayer only; experimental)','legacy':'v1 recipe compatibility'},
        'documents':{name:hashlib.sha256((resources/name).read_bytes()).hexdigest() for name in ('HelpContent.json','ReleaseNotes.txt','ResearchReferences.json')}
        },ensure_ascii=False,indent=2)+'\n')
    runtime=Path(sys.base_prefix);python=resources/'python';(python/'bin').mkdir(parents=True)
    shutil.copy2(runtime/'bin/python3.12',python/'bin/python3')
    shutil.copytree(runtime/'lib/python3.12',python/'lib/python3.12',ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','ensurepip','turtledemo'))
    site=python/'lib/python3.12/site-packages';site.mkdir()
    local=PORT/'.venv/lib/python3.12/site-packages'
    prefixes=('numpy','rawpy','tifffile','imagecodecs','lensfunpy')
    for p in local.iterdir():
        if p.name.startswith(prefixes):
            if p.is_dir():shutil.copytree(p,site/p.name,ignore=shutil.ignore_patterns('__pycache__','tests'))
            else:shutil.copy2(p,site/p.name)
    backend=resources/'backend';backend.mkdir()
    if args.release:
        subprocess.run([sys.executable,str(ROOT/'macos/compile_backend.py'),'--source',str(PORT),'--destination',str(backend),'--work',str(stage/'compile-work')],check=True)
        shutil.rmtree(stage/'compile-work')
        subprocess.run(['xcrun','strip','-S',str(contents/'MacOS/toMONO')],check=True)
    else:
        for name in ('tomono_cli.py','conversion_service.py','recipe.py','metadata_params.py','raw_input.py','dng_reader.py','dng_layout.py','dng_writer.py','display_render.py','monochrome_preview.py','execution_log.py','defect_map.py','lens_correction.py','channel_response.py','pure_narrowband.py','detail_reconstruction.py','lmmse_reconstruction.py','preview_inspection.py'):
            shutil.copy2(PORT/name,backend/name)
    catalog_env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([sys.executable,str(PORT/'lens_correction.py'),'--catalog',str(resources/'LensCatalog.json')],env=catalog_env,check=True)
    shutil.copy2(PORT/'robertson_table.json',backend/'robertson_table.json')
    native=backend/'build/native-macos';native.mkdir(parents=True)
    for library in ('libtomono_core.dylib','libtomono_detail.dylib','libtomono_lmmse.dylib'):
        shutil.copy2(PORT/'build/native-macos'/library,native/library)
    tool=Path(shutil.which('exiftool')).resolve();dest=resources/'exiftool';dest.mkdir();shutil.copy2(tool,dest/'exiftool')
    shutil.copytree(tool.parent/'lib',dest/'lib')
    # Preserve the notices shipped by each selected runtime dependency.
    notices=['toMONO 1.2 正式版 — 项目与第三方组件许可\n\n源码：https://github.com/easonzhangbin/toMONO\n项目原创源码：GPL-3.0-only。第三方组件保留各自许可。\n', (ROOT/'LICENSE').read_text()]
    license_paths=[runtime/'lib/python3.12/LICENSE.txt']
    for directory in sorted(local.glob('*.dist-info')):
        if directory.name.startswith(prefixes):
            metadata=(directory/'METADATA').read_text(errors='replace')
            details='\n'.join(line for line in metadata.splitlines() if line.startswith(('Name:','Version:','License-Expression:','Home-page:')))
            notices.append('\n'+details+'\n')
            license_paths.extend(p for p in sorted(directory.rglob('*')) if p.is_file() and ('license' in str(p.relative_to(directory)).lower() or 'copying' in p.name.lower()))
    for path in license_paths:
        notices.append('\n===== '+str(path.relative_to(runtime) if path.is_relative_to(runtime) else path.relative_to(local))+' =====\n'+path.read_text(errors='replace'))
    pod=(tool.parent/'lib/Image/ExifTool.pod').read_text(errors='replace')
    credit=pod[pod.find('=head1 AUTHOR'):]
    if not credit:credit=pod[-6000:]
    notices.append('\n===== ExifTool =====\n'+credit)
    for path in sorted((ROOT/'macos/assets/licenses').glob('*')):
        if path.is_file():notices.append('\n===== '+path.name+' =====\n'+path.read_text(errors='replace'))
    (resources/'ThirdPartyNotices.txt').write_text('\n'.join(notices),encoding='utf-8')
    # Verify the private runtime before publishing the bundle.
    env=dict(os.environ,PYTHONHOME=str(python),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',TOMONO_EXIFTOOL=str(dest/'exiftool'))
    env.pop('PYTHONPATH',None)
    subprocess.run([str(python/'bin/python3'),'-s','-c','import rawpy,numpy,tifffile,imagecodecs,lensfunpy,channel_response,pure_narrowband,detail_reconstruction,lmmse_reconstruction,preview_inspection; from recipe import Recipe; assert Recipe().detail_mode=="directional"; assert len(lensfunpy.Database(load_common=False).lenses)>0; channel_response.native_core(); pure_narrowband.native_core(); detail_reconstruction._library(); lmmse_reconstruction._library(); print("内置运行环境：通过")'],env=env,cwd=backend,check=True)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(stage)],check=True,capture_output=True)
    if app.exists():
        backup=app.parent/('toMONO.previous-'+uuid.uuid4().hex[:8]+'.app');app.rename(backup)
    stage.rename(app);print('应用已构建：',app)
except Exception:
    print('构建未完成，保留现场：',stage,file=sys.stderr);raise
