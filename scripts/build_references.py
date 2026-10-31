"""Build only the published frozen references; do not mutate their sources."""
from pathlib import Path
import hashlib
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]
for name in ('detail_resolution_20261031', 'detail_resolution_v2_20261031'):
    directory = ROOT / 'analysis' / name
    manifest = json.loads((directory / 'kernel_manifest.json').read_text())
    for filename in ('kernels.py', 'detail_native.c'):
        digest = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        assert digest == manifest['file_sha256'][filename], filename
    spec = importlib.util.spec_from_file_location(name, directory / 'kernels.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._library()
    print(name + ': source verified, reference library ready')
