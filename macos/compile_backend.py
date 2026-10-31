"""Compile GPL-licensed project modules for the local application bundle."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from setuptools import Extension,Distribution
from Cython.Build import cythonize

MODULES=['conversion_service','recipe','metadata_params','raw_input','dng_reader','dng_layout','dng_writer','display_render','execution_log','defect_map','lens_correction','channel_response','pure_narrowband','detail_reconstruction']
ENTRY={'tomono_worker':'tomono_cli','tomono_preview':'monochrome_preview'}

def build(source,destination,work):
    (work/'src').mkdir(parents=True,exist_ok=True)
    extensions=[];manifest=[]
    for name,original in [(x,x) for x in MODULES]+list(ENTRY.items()):
        original=source/(original+'.py');copy=work/'src'/(name+'.py');shutil.copyfile(original,copy)
        extensions.append(Extension(name,[str(copy)],extra_compile_args=['-O2','-mmacosx-version-min=14.0','-fno-fast-math','-ffp-contract=off'],extra_link_args=['-mmacosx-version-min=14.0']))
        manifest.append(dict(module=name,source_sha256=hashlib.sha256(original.read_bytes()).hexdigest()))
    previous=os.environ.get('MACOSX_DEPLOYMENT_TARGET');os.environ['MACOSX_DEPLOYMENT_TARGET']='14.0'
    try:
        compiled=cythonize(extensions,compiler_directives=dict(language_level=3,annotation_typing=False,infer_types=False,binding=True),build_dir=str(work/'cython'),quiet=True)
        dist=Distribution({'name':'tomono-private-backend','ext_modules':compiled})
        command=dist.get_command_obj('build_ext');command.build_lib=str(work/'lib');command.build_temp=str(work/'obj');command.parallel=4;command.ensure_finalized();command.run()
    finally:
        if previous is None:os.environ.pop('MACOSX_DEPLOYMENT_TARGET',None)
        else:os.environ['MACOSX_DEPLOYMENT_TARGET']=previous
    for record in manifest:
        files=list((work/'lib').glob(record['module']+'.*.so'))
        if len(files)!=1:raise RuntimeError('编译产物不唯一：'+record['module'])
        subprocess.run(['xcrun','strip','-S',str(files[0])],check=True)
        shutil.copyfile(files[0],destination/files[0].name);record['binary']=files[0].name
    for module,script in ENTRY.items():
        (destination/(script+'.py')).write_text('import sys\nfrom '+module+' import main\nif __name__ == "__main__":\n    sys.exit(main())\n')
    (destination/'BuildManifest.json').write_text(json.dumps(dict(mode='compiled-project-modules',source_license='GPL-3.0-only',source_repository='https://github.com/easonzhangbin/toMONO',modules=manifest),indent=2)+'\n')
    print('已编译自研后台模块：',len(manifest))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--work',type=Path,required=True);args=parser.parse_args()
    build(args.source,args.destination,args.work)
