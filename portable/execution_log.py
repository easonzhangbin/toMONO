"""Append-only local diagnostic events, shared with the native session log."""
import datetime,json,os,traceback,uuid
from pathlib import Path
_path=None
def configure(path=None):
    global _path
    chosen=path or os.environ.get('TOMONO_EXECUTION_LOG')
    if chosen:_path=Path(chosen).expanduser()
    elif _path is None:
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        _path=Path.home()/'Library/Application Support/toMONO/Logs'/f'worker-{stamp}-{uuid.uuid4().hex[:8]}.jsonl'
    return str(_path)
def event(stage,level='info',**fields):
    try:
        path=Path(configure());path.parent.mkdir(parents=True,exist_ok=True)
        row={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds'),'pid':os.getpid(),'level':level,'stage':stage,**fields}
        data=(json.dumps(row,ensure_ascii=False,default=str)+'\n').encode()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:os.write(fd,data)
        finally:os.close(fd)
    except Exception:pass  # Logging failure must not change photo save status.
def failure(stage,exc,**fields):event(stage,'error',error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc(),**fields)
