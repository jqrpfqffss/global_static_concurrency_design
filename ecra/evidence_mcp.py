"""Read-only stdio MCP adapter for the same paged EvidenceProvider as Studio.

The database is fixed at process startup. Tools accept no filesystem paths,
SQL, shell commands, URLs or writes. This is evidence transport, not an agent.
"""
import argparse
import json
from pathlib import Path
import sys

from .scan_store import EvidenceProvider

TOOLS = [dict(name='evidence', description='完整静态证据分页。root/path 首次定位；node 继续读取子节点；text=true 读取长文本。每页含总数、SHA256和 next_offset；必须读到游标为空。',
    inputSchema=dict(type='object',properties=dict(root=dict(type='string',enum=['facts','report','provenance']),
        path=dict(type='array',items=dict(anyOf=[dict(type='string'),dict(type='integer',minimum=0)])),
        node=dict(type='integer',minimum=1),text=dict(type='boolean'),
        offset=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=200)),additionalProperties=False),
    annotations=dict(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False))]


def evidence(provider, arguments):
    if not isinstance(arguments,dict) or set(arguments)-{'root','path','node','text','offset','limit'}:
        raise ValueError('证据参数未知')
    root, path = arguments.get('root','facts'), arguments.get('path',[])
    if root not in {'facts','report','provenance'} or not isinstance(path,list) or any(type(k) not in {str,int} for k in path):
        raise ValueError('证据根/路径无效')
    node = arguments.get('node')
    if node is not None and (type(node) is not int or node<1):
        raise ValueError('证据节点无效')
    node = node if node is not None else provider.resolve(root,path)
    offset, limit = arguments.get('offset',0), arguments.get('limit',50)
    provider._bounds(offset,limit)
    return provider.text(node,offset=offset,limit=limit) if arguments.get('text',False) else provider.node(node,offset=offset,limit=limit)


def dispatch(provider, request):
    if not isinstance(request,dict) or request.get('jsonrpc')!='2.0':
        raise ValueError('无效 JSON-RPC')
    method, params = request.get('method'), request.get('params',{})
    if method=='initialize':
        supported={'2024-11-05','2025-03-26','2025-06-18','2025-11-25'}
        requested=params.get('protocolVersion')
        return dict(protocolVersion=requested if requested in supported else '2025-06-18',
            capabilities=dict(tools=dict(listChanged=False)),serverInfo=dict(name='ECRA immutable evidence',version='1.0.0'))
    if method=='ping':
        return {}
    if method=='tools/list':
        return dict(tools=TOOLS)
    if method=='tools/call':
        if params.get('name') != 'evidence':
            raise ValueError('未知只读工具')
        try:
            result = evidence(provider,params.get('arguments',{}))
            return dict(content=[dict(type='text',text=json.dumps(result,ensure_ascii=True))],isError=False)
        except (KeyError,ValueError,TypeError) as exc:
            return dict(content=[dict(type='text',text=str(exc))],isError=True)
    if method and method.startswith('notifications/'):
        return None
    raise LookupError('未知 MCP 方法')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args(argv)
    provider=EvidenceProvider(args.database)
    provider.metadata()
    for stream in (sys.stdin,sys.stdout):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='strict')
    while True:
        line=sys.stdin.readline(1024*1024+1)
        if not line:
            return 0
        request=None
        try:
            if len(line)>1024*1024:
                while line and not line.endswith('\n'):
                    line=sys.stdin.readline(65536)
                raise ValueError('MCP 请求超出预算')
            request=json.loads(line)
            result=dispatch(provider,request)
            if 'id' not in request:
                continue
            reply=dict(jsonrpc='2.0',id=request['id'],result=result)
        except (ValueError,TypeError,KeyError,LookupError,RecursionError) as exc:
            reply=dict(jsonrpc='2.0',id=request.get('id') if isinstance(request,dict) else None,
                error=dict(code=-32601 if isinstance(exc,LookupError) else -32602,message=str(exc)))
        print(json.dumps(reply,ensure_ascii=True),flush=True)


if __name__=='__main__':raise SystemExit(main())
