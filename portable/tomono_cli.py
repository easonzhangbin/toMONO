"""toMONO：简体中文命令行及原生界面工作进程。"""
import argparse,json,sys,signal
from pathlib import Path
from recipe import Recipe
from conversion_service import convert_and_save,Cancelled
from execution_log import configure,event,failure

class ChineseParser(argparse.ArgumentParser):
    def format_usage(self):return super().format_usage().replace('usage:','用法：',1)
    def format_help(self):return super().format_help().replace('usage:','用法：',1)
    def error(self,message):
        message=message.replace('the following arguments are required:','缺少必填参数：').replace('unrecognized arguments:','无法识别的参数：').replace('expected one argument','需要一个参数值')
        self.print_usage(sys.stderr);self.exit(2,f'参数错误：{message}\n')

def main():
    parser=ChineseParser(add_help=False,description='toMONO：RAW单通道响应与细节重建、独立窄带输出及拍摄信息保留。')
    parser._positionals.title='参数';parser._optionals.title='选项'
    parser.add_argument('-h','--help',action='help',help='显示帮助并退出')
    parser.add_argument('input',type=Path,nargs='?',help='输入相机RAW（由LibRaw识别）')
    parser.add_argument('-o','--output',type=Path,help='新输出DNG，拒绝覆盖原图或已有结果')
    parser.add_argument('--report',type=Path,help='处理记录JSON')
    parser.add_argument('--recipe',type=Path,help='加载配方JSON')
    parser.add_argument('--save-default-recipe',type=Path,help='保存默认配方后退出')
    parser.add_argument('--json',action='store_true',help='向界面输出结构化进度')
    parser.add_argument('--log',type=Path,help='追加执行日志JSONL；默认仅保存在本机')
    args=parser.parse_args()
    log_path=configure(args.log)
    event('conversion_requested',input=str(args.input),output=str(args.output),recipe=str(args.recipe))
    cancel_requested=False
    def emit(value):
        # Cancellation is observed before publication, never after a saved DNG.
        if value['type']=='progress' and cancel_requested:raise Cancelled('用户取消')
        if args.json:print(json.dumps(value,ensure_ascii=False),flush=True)
        elif value['type']=='progress':print(value['phase']+'……',flush=True)
    def cancelled(signum,frame):
        nonlocal cancel_requested
        cancel_requested=True
    signal.signal(signal.SIGINT,cancelled)
    try:
        if args.save_default_recipe:
            Recipe().save(args.save_default_recipe);print('默认配方已保存');return 0
        if args.input is None or args.output is None:parser.error('请指定输入文件和-o输出路径')
        recipe=Recipe.load(args.recipe) if args.recipe else Recipe()
        result=convert_and_save(args.input,args.output,recipe,args.report,emit)
        result['execution_log']=log_path
        if args.json:emit(result)
        else:
            print('DNG已保存：'+result['output'])
            print('像素回读与文件结构检查：通过')
            if result['sidecar_saved']:print('处理记录已保存：'+result['report'])
            for warning in result['warnings']:print('提示：'+warning)
        return 0
    except Cancelled:
        event('conversion_cancelled')
        emit({'type':'result','state':'cancelled','dng_saved':False,'message':'已取消，未保存新DNG'})
        if not args.json:print('已取消，未保存新DNG')
        return 130
    except Exception as exc:
        failure('conversion_failed',exc,input=str(args.input),output=str(args.output))
        if args.json:emit({'type':'result','state':'failed','dng_saved':False,'message':str(exc)})
        else:print('转换失败：'+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
