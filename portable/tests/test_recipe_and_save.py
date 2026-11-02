import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
PORT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PORT))
from recipe import Recipe
from conversion_service import convert_and_save
class RecipeTests(unittest.TestCase):
    def test_roundtrip_preserves_exact_manual_values(self):
        r=Recipe(green_mode='manual',compensation=1.2309999465942383,focus_blue=True)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'配方.json';r.save(p);self.assertEqual(Recipe.load(p),r)
    def test_rejects_unknown_or_invalid_parameters(self):
        for fields in ({'algorithm':'VNG'},{'compensation':float('nan')},{'version':3},{'focus_red':1},{'green_mode':'other'},{'typo':5},{'detail_mode':'RGB-guided'},{'detail_mode':None}):
            with self.assertRaises(ValueError):Recipe.from_dict(fields)
    def test_new_defaults_use_d10_without_changing_saved_v2_migration(self):
        self.assertEqual((Recipe().version,Recipe().detail_mode),(2,'directional'))
        self.assertEqual(Recipe.from_dict({'version':2}).detail_mode,'spectral')
        self.assertEqual(Recipe.from_dict(Recipe().to_dict()),Recipe())
    def test_lmmse_is_available_only_for_ordinary_responses(self):
        for response in ('green','mix'):
            r=Recipe.from_dict({'version':2,'detail_mode':'lmmse','response_mode':response})
            self.assertEqual((r.detail_mode,r.response_mode),('lmmse',response))
            self.assertEqual(Recipe.from_dict(r.to_dict()),r)
        for response in ('narrow_red','narrow_green','narrow_blue'):
            with self.assertRaisesRegex(ValueError,'不能用于窄带独立纯通道'):
                Recipe.from_dict({'version':2,'detail_mode':'lmmse','response_mode':response})
    def test_old_recipes_migrate_without_changing_their_interpolation(self):
        for data in ({},{'version':1},{'algorithm':'EdgeAware','narrow_interpolation':'linear'}):
            migrated=Recipe.from_dict(data)
            self.assertEqual((migrated.version,migrated.detail_mode),(2,'legacy'))
            self.assertEqual(migrated.algorithm,data.get('algorithm','Bicubic'))
            self.assertEqual(migrated.narrow_interpolation,data.get('narrow_interpolation','cubic'))
        self.assertEqual(Recipe.from_dict({'version':1,'detail_mode':'directional'}).detail_mode,'directional')

class SaveStatusTests(unittest.TestCase):
    def run_small_conversion(self,directory,report,progress=None):
        import numpy as np
        from types import SimpleNamespace
        root=Path(directory);source=root/'source.dng';source.write_bytes(b'source-not-edited')
        output=root/'result.dng'
        frame=SimpleNamespace(samples=np.full((8,8),2000,dtype=np.uint16),metadata={
            'black_level_by_libraw_channel':[1023]*4,'white_level':16383,
            'visible_area':{'top':0,'left':0,'height':8,'width':8},'cfa_codes_full_origin':[[0,1],[1,2]]})
        parameters={'green_compensation':1.231,'camera_white':[.25,1,.67],'focus_red':True,'focus_blue':False}
        def writer(src,dst,*args):
            Path(dst).write_bytes(b'validated-dng');return {'metadata_validation':{'Validate':'OK'}}
        with patch('conversion_service.parameters_from_dng',return_value=parameters),patch('conversion_service.decode_sensor',return_value=frame),patch('conversion_service.source_structure',return_value={}),patch('conversion_service.write_dng',side_effect=writer):
            return convert_and_save(source,output,report_path=report,progress=progress)
    def test_sidecar_failure_does_not_report_dng_failure(self):
        with tempfile.TemporaryDirectory() as d:
            blocker=Path(d)/'not-a-folder';blocker.write_text('keep')
            result=self.run_small_conversion(d,blocker/'report.json')
            self.assertEqual(result['state'],'saved_with_warning')
            self.assertTrue(result['dng_saved']);self.assertFalse(result['sidecar_saved'])
            self.assertEqual((Path(d)/'result.dng').read_bytes(),b'validated-dng')
            self.assertEqual(blocker.read_text(),'keep')
    def test_cancel_before_publish_removes_temporary_and_does_not_save(self):
        from conversion_service import Cancelled
        def cancel(event):
            if event['progress']>=.94:raise Cancelled()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Cancelled):self.run_small_conversion(d,Path(d)/'report.json',cancel)
            self.assertFalse((Path(d)/'result.dng').exists());self.assertEqual(list(Path(d).glob('.tomono-*')),[])
    def test_success_report_contains_recipe(self):
        with tempfile.TemporaryDirectory() as d:
            result=self.run_small_conversion(d,Path(d)/'report.json')
            saved=json.loads((Path(d)/'report.json').read_text())
            self.assertTrue(result['sidecar_saved']);self.assertTrue(saved['sidecar_saved'])
            self.assertEqual(saved['recipe']['version'],2)
            self.assertEqual(saved['recipe']['detail_mode'],'directional')
            self.assertEqual(list(Path(d).glob('.tomono-*')),[])
    def test_failed_report_serialization_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'report.json'
            with patch('conversion_service.json.dump',side_effect=OSError('simulated interrupted write')):
                result=self.run_small_conversion(d,report)
            self.assertEqual(result['state'],'saved_with_warning')
            self.assertTrue(result['dng_saved']);self.assertFalse(report.exists())
            self.assertEqual(list(Path(d).glob('.tomono-*')),[])
    def test_existing_report_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'report.json';report.write_text('keep-existing-report')
            result=self.run_small_conversion(d,report)
            self.assertEqual(result['state'],'saved_with_warning')
            self.assertEqual(report.read_text(),'keep-existing-report')

class WorkerCancellationTests(unittest.TestCase):
    def test_late_cancel_keeps_saved_result(self):
        import tomono_cli,signal,io
        from contextlib import redirect_stdout
        previous=signal.getsignal(signal.SIGINT)
        def committed(*args):
            signal.raise_signal(signal.SIGINT)
            return {'type':'result','state':'saved','dng_saved':True,'sidecar_saved':True}
        try:
            out=io.StringIO()
            with patch.object(sys,'argv',['worker','input.dng','-o','output.dng','--json']),patch('tomono_cli.convert_and_save',side_effect=committed),redirect_stdout(out):
                self.assertEqual(tomono_cli.main(),0)
            self.assertEqual(json.loads(out.getvalue())['state'],'saved')
        finally:signal.signal(signal.SIGINT,previous)
