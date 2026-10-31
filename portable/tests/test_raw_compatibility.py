import ctypes,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np,tifffile
import rawpy
from types import SimpleNamespace
from unittest.mock import patch
PORT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PORT))
from dng_layout import select_raw_ifd
from metadata_params import parameters_from_dng
from dng_writer import source_structure
from raw_input import decode_sensor

class DNGLayoutTests(unittest.TestCase):
    def test_preview_root_raw_subifd_and_global_metadata_are_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'subifd.dng'
            with tifffile.TiffWriter(path) as t:
                t.write(np.zeros((4,4,3),np.uint8),photometric='rgb',subfiletype=1,subifds=1,metadata=None,
                    extratags=[(50706,'B',4,(1,4,0,0),False),(50708,'s',0,'Synthetic Camera',False),
                    (271,'s',0,'Test',False),(272,'s',0,'Synthetic Camera',False),(274,'H',1,8,False),
                    (50728,'2I',3,(1,2,1,1,2,3),False)])
                t.write(np.full((12,12),1000,np.uint16),photometric=32803,metadata=None,
                    extratags=[(33421,'H',2,(2,2),False),(33422,'B',4,(0,1,1,2),False),
                    (50829,'I',4,(2,2,10,10),False),(50719,'2I',2,(0,1,0,1),False),
                    (50720,'2I',2,(8,1,8,1),False)])
            with tifffile.TiffFile(path) as t:self.assertEqual(select_raw_ifd(t).ifd_path,'0.0')
            parameters=parameters_from_dng(path)
            self.assertEqual(parameters['model'],'Synthetic Camera');self.assertEqual(parameters['preset'],'generic_bayer')
            self.assertEqual(parameters['green_compensation'],0)
            structure=source_structure(path,(12,12))
            self.assertEqual(structure['Orientation'],8);self.assertEqual(structure['active_area'],[2,2,10,10])
            self.assertEqual(structure['crop_size'],[8,8])

class GeneralCoreTests(unittest.TestCase):
    def test_16_bit_green_signal_and_first_row_across_bayer_patterns(self):
        lib=ctypes.CDLL(str(PORT/'build/native-macos/libtomono_core.dylib'))
        pointer=ctypes.POINTER(ctypes.c_uint16)
        f=lib.tomono_bicubic_green_plane_range
        f.argtypes=[pointer,ctypes.c_size_t,pointer,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        f.restype=ctypes.c_int
        for pattern in ([0,1,1,2],[2,1,1,0],[1,0,2,1],[1,2,0,1]):
            with self.subTest(pattern=pattern):
                samples=np.full((16,16),1000,np.uint16)
                for y in range(2):
                    for x in range(2):
                        if pattern[y*2+x]==1:samples[y::2,x::2]=60000
                output=np.empty_like(samples)
                self.assertEqual(f(samples.ctypes.data_as(pointer),samples.size,output.ctypes.data_as(pointer),output.size,16,16,(ctypes.c_uint8*4)(*pattern),0,0,65535),0)
                np.testing.assert_array_equal(output,np.full_like(output,60000))

class ExecutionLogTests(unittest.TestCase):
    def test_cli_failure_keeps_complete_local_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/'execution.jsonl'
            result=subprocess.run([sys.executable,str(PORT/'tomono_cli.py'),str(root/'missing.ARW'),'-o',str(root/'result.dng'),'--log',str(log),'--json'],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            events=[json.loads(line) for line in log.read_text().splitlines()]
            error=next(row for row in events if row['stage']=='conversion_failed')
            self.assertEqual(error['error_type'],'ValueError');self.assertIn('conversion_service.py',error['traceback'])
            self.assertFalse((root/'result.dng').exists())

class LibRawLayoutDispatchTests(unittest.TestCase):
    def test_non_bayer_layouts_use_linear_libraw_without_rgb_jpeg_desaturation(self):
        image=np.zeros((10,12,3),np.uint16);image[:,:,1]=np.arange(120,dtype=np.uint16).reshape(10,12)+5000
        sizes=SimpleNamespace(top_margin=0,left_margin=0,height=10,width=12,crop_left_margin=0,crop_top_margin=0,crop_width=12,crop_height=10,flip=0)
        for pattern,kind in ((None,rawpy.RawType.Flat),(None,rawpy.RawType.Stack),(np.zeros((32,32)),rawpy.RawType.Flat)):
            raw=SimpleNamespace(sizes=sizes,color_desc=b'RGBG',raw_pattern=pattern,raw_type=kind,
                black_level_per_channel=[512]*4,white_level=16383,camera_white_level_per_channel=None,camera_whitebalance=[2,1,1.5,1])
            with self.subTest(pattern=None if pattern is None else pattern.shape):
                from unittest.mock import MagicMock
                context=MagicMock();context.__enter__.return_value=raw
                raw.postprocess=MagicMock(return_value=image)
                with patch('raw_input.rawpy.imread',return_value=context):frame=decode_sensor('sample.RAW')
                np.testing.assert_array_equal(frame.samples,image[:,:,1])
                self.assertTrue(frame.metadata['linear_reconstruction'])
                self.assertEqual(raw.postprocess.call_args.kwargs['gamma'],(1,1))
                self.assertEqual(raw.postprocess.call_args.kwargs['user_wb'],[1,1,1,1])
                self.assertTrue(raw.postprocess.call_args.kwargs['no_auto_bright'])
    def test_xtrans_green_lattice_preserves_measured_green_signal(self):
        pattern=np.array([[1,0,1,1,2,1],[2,1,2,0,1,0],[1,0,1,1,2,1],[1,2,1,1,0,1],[0,1,0,2,1,2],[1,2,1,1,0,1]],np.uint8)
        samples=np.where(np.tile(pattern,(3,3))==1,60000,1000).astype(np.uint16)
        from unittest.mock import MagicMock
        raw=SimpleNamespace(sizes=SimpleNamespace(top_margin=0,left_margin=0,height=18,width=18,crop_left_margin=0,crop_top_margin=0,crop_width=18,crop_height=18,flip=0),
            color_desc=b'RGBG',raw_pattern=pattern,raw_type=rawpy.RawType.Flat,raw_color=lambda y,x:int(pattern[y%6,x%6]),raw_image=samples,
            black_level_per_channel=[0]*4,white_level=65535,camera_white_level_per_channel=None,camera_whitebalance=[1]*4,num_colors=3,postprocess=MagicMock())
        context=MagicMock();context.__enter__.return_value=raw
        with patch('raw_input.rawpy.imread',return_value=context):frame=decode_sensor('xtrans.RAF')
        self.assertEqual(frame.metadata['sensor_layout'],'green_lattice');raw.postprocess.assert_not_called()
        lib=ctypes.CDLL(str(PORT/'build/native-macos/libtomono_core.dylib'));f=lib.tomono_green_lattice_plane
        pointer=ctypes.POINTER(ctypes.c_uint16)
        f.argtypes=[pointer,ctypes.c_size_t,pointer,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        output=np.empty_like(samples)
        self.assertEqual(f(samples.ctypes.data_as(pointer),samples.size,output.ctypes.data_as(pointer),output.size,18,18,(ctypes.c_uint8*36)(*pattern.flat),6,6,65535),0)
        np.testing.assert_array_equal(output,np.full_like(output,60000))


class MonochromeInputTests(unittest.TestCase):
    def test_linear_single_channel_dng_uses_valid_level_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'linear.dng'
            image=np.full((200,300),1000,np.uint16)
            tifffile.imwrite(path,image,photometric=34892,metadata=None,extratags=[
                (271,'s',0,'Synthetic',False),(272,'s',0,'Monochrome',False),(50708,'s',0,'Synthetic Monochrome',False),
                (50706,'B',4,(1,4,0,0),False),(50707,'B',4,(1,3,0,0),False),
                (50714,'2I',1,(64,1),False),(50717,'I',1,16383,False)])
            frame=decode_sensor(path)
            self.assertEqual(frame.metadata['cfa_libraw_channels_full_origin'],[[0]])
            np.testing.assert_array_equal(frame.samples,image)
