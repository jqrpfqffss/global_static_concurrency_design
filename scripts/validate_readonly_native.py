"""Actual Windows ACL-read-only firmware scan, original/current full comparison.

Only a new owned source copy receives ACL changes, restored in finally. This
proves applicable compile-database scans, not a read-only volume, malicious
owner-resistant sandbox, production write-guard integration or a new G2 project.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import traceback

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.workspace import no_links,studio_data_root
from ecra.scan_store import publish_json_scan
from scripts.compare_native_graphs import compare

ACL_SCRIPT=r'''
param([string]$Mode,[string]$Root,[string]$Record)
$ErrorActionPreference='Stop'
$owned=[IO.Path]::GetFullPath($Root)
if ([IO.Path]::GetFileName($owned) -cne 'firmware' -or
    [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Record)) -cne [IO.Path]::GetDirectoryName($owned)) {
    throw 'ACL changes must be confined to the owned firmware copy and its adjacent receipt'
}
function Inventory {
    $items=@(Get-Item -LiteralPath $owned -Force)+@(Get-ChildItem -LiteralPath $owned -Force -Recurse)
    @($items | Sort-Object { $_.FullName.Length } | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) {throw 'Reparse point in controlled copy'}
        @{path=$_.FullName;directory=[bool]$_.PSIsContainer;sddl=(Get-Acl -LiteralPath $_.FullName).Sddl}
    })
}
if ($Mode -ceq 'Protect') {
    if (Test-Path -LiteralPath $Record) {throw 'Preserve existing ACL backup'}
    # Windows canonicalizes AUTO_INHERITED on Set-Acl. Normalize only the new
    # owned copy before taking the restoration baseline, keeping all ACEs.
    foreach ($row in (Inventory)) {
        $acl=Get-Acl -LiteralPath $row.path
        Set-Acl -LiteralPath $row.path -AclObject $acl
    }
    $before=Inventory
    $before | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Record -Encoding utf8
    $acl=Get-Acl -LiteralPath $owned
    $rights=[Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    $inherit=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $rule=[Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new('S-1-1-0'),$rights,$inherit,
        [Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Deny)
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $owned -AclObject $acl
} elseif ($Mode -ceq 'Restore') {
    $before=Get-Content -LiteralPath $Record -Raw | ConvertFrom-Json
    foreach ($row in $before) {
        $path=[IO.Path]::GetFullPath($row.path)
        if ($path -cne $owned -and -not $path.StartsWith($owned+'\',[StringComparison]::OrdinalIgnoreCase)) {
            throw 'ACL backup escapes owned copy'
        }
        $acl=Get-Acl -LiteralPath $path
        $acl.SetSecurityDescriptorSddlForm($row.sddl,[Security.AccessControl.AccessControlSections]::Access)
        Set-Acl -LiteralPath $path -AclObject $acl
    }
    $now=Inventory
    foreach ($row in $before) {
        $match=@($now | Where-Object { $_.path -ceq $row.path })
        if ($match.Count -ne 1 -or $match[0].sddl -cne $row.sddl) {throw 'ACL restore differs from original descriptor'}
    }
} elseif ($Mode -ceq 'Inspect') {
    Inventory | ConvertTo-Json -Depth 4
} else {throw 'Invalid controlled ACL action'}
'''


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024**2):h.update(block)
    return h.hexdigest()


def inventory(root):
    result={}
    for p in root.rglob('*'):
        no_links(p)
        if p.is_file():result[p.relative_to(root).as_posix()]=[sha(p),p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_file_attributes]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['engine','original-engine','firmware','compile-database','config','work']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='nt':parser.error('Actual Windows ACL enforcement required')
    engine=no_links(args.engine);original_engine=no_links(args.original_engine)
    source=no_links(args.firmware);work=studio_data_root(args.work)
    if any(work==p or work.is_relative_to(p) or p.is_relative_to(work) for p in [source,engine,original_engine]):
        raise ValueError('Owned test roots must not overlap original source or engines')
    if work.exists():raise FileExistsError('Preserve prior read-only attempts; choose a fresh work root')
    pwsh=shutil.which('pwsh')
    if not pwsh:raise ValueError('PowerShell7 is required for this development acceptance script')
    original=inventory(source);work.mkdir(parents=True)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    copied=work/'firmware';shutil.copytree(source,copied)
    for p in copied.rglob('*'):
        if p.is_file():os.chmod(p,stat.S_IREAD|stat.S_IWRITE)
    before=inventory(copied)
    if {k:v[:3] for k,v in original.items()}!={k:v[:3] for k,v in before.items()}:
        raise ValueError('Copied firmware bytes/size/mtime differ')
    def remap(value):
        if isinstance(value,str):
            for spelling in [str(source),source.as_posix()]:value=value.replace(spelling,str(copied))
            return value
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        return value
    inputs=work/'input-contract';inputs.mkdir()
    db=inputs/'compile_commands.json';db.write_text(json.dumps(remap(json.loads(args.compile_database.read_text('utf-8'))),indent=2),'utf-8')
    import yaml
    cfg=yaml.safe_load(args.config.read_text('utf-8'))
    cfg['project']['root']=str(copied);cfg['analysis']['compile_database']=str(db)
    cfg['analysis']['output']=dict(location='custom',custom_dir=str(work/'original-data'))
    config=inputs/'semantics.yaml';config.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),'utf-8')
    acl_script=work/'acl.ps1';acl_script.write_text(ACL_SCRIPT,'utf-8')
    backup=work/'acl-before.json';commands=[];restored=False;started=time.monotonic()
    result=dict(passed=False,scope=__doc__,commands=commands,firmware=str(source),owned_copy=str(copied),
                controller_sha256=sha(work/'controller.py'),engine=str(engine),original_engine=str(original_engine),
                native_g2='NOT_ANOTHER_PROJECT',readonly_volume='NOT_VERIFIED',production_guard='NOT_INTEGRATED')
    def run(argv,name,expected=0):
        output=work/(name+'.log')
        with output.open('xb') as out:code=subprocess.call(list(map(str,argv)),stdout=out,stderr=subprocess.STDOUT)
        commands.append(dict(name=name,command=list(map(str,argv)),exit_code=code,log=str(output),sha256=sha(output)))
        if code!=expected:raise RuntimeError(name+' failed; see '+str(output))
        return output
    def acl(mode,name):return run([pwsh,'-NoProfile','-File',acl_script,'-Mode',mode,'-Root',copied,'-Record',backup],name)
    def probe(name):
        code='import pathlib,sys\ntry:pathlib.Path(sys.argv[1]).write_bytes(b"probe")\nexcept PermissionError:raise SystemExit(0)\nraise SystemExit(5)'
        run([sys.executable,'-B','-X','utf8','-c',code,copied/'ecra-write-probe.tmp'],name)
        if (copied/'ecra-write-probe.tmp').exists():raise ValueError('ACL write probe unexpectedly created a file')
    try:
        acl('Protect','01-protect')
        def acl_rows(path):return {row['path']:row['sddl'] for row in json.loads(path.read_text('utf-8-sig'))}
        acl_before=acl_rows(acl('Inspect','02-protected-before'));probe('03-write-denied-before')
        for mode,current,data,observer in [('legacy',original_engine,work/'original-data',work/'original-run'),
                                           ('canonical',engine,work/'new-data',work/'new-run')]:
            run([sys.executable,'-B','-X','utf8',engine/'scripts/measure_native_golden.py','--engine',current,
                 '--config',config,'--data-root',data,'--work',observer,'--mode',mode,'--limit-gib','2'],mode+'-scan')
            receipt=json.loads((observer/'execution.json').read_text('utf-8'))
            if not receipt['complete'] or not receipt['validity']['analysis_valid']:raise ValueError(mode+' native scan invalid')
            result[mode]=receipt
        probe('06-write-denied-after');acl_after=acl_rows(acl('Inspect','07-protected-after'))
        if acl_before!=acl_after:raise ValueError('Protected tree ACLs changed during scan')
        old=Path(result['legacy']['output']);reference=work/'original.db'
        publish_json_scan(reference,old/'facts.json',old/'reports/global_static_concurrency.json',scan_id='readonly-original',project_id='readonly')
        comparison=compare(reference,Path(result['canonical']['output'])/'scan.db',envelope=work/'runtime-envelope.jsonl')
        (work/'semantic-comparison.json').write_text(json.dumps(comparison,indent=2),'utf-8')
        if not comparison['passed']:raise ValueError('Complete facts/report comparison differs')
        if inventory(source)!=original or inventory(copied)!=before:raise ValueError('Original or protected copy changed')
        result.update(passed=True,original_files=len(original),original_unchanged=True,protected_copy_unchanged=True,
                      acl_enforced_before_after=True,acl_unchanged=True,comparison=comparison)
    except BaseException:result['error']=traceback.format_exc();raise
    finally:
        try:
            if backup.exists():acl('Restore','08-restore');restored=True
        finally:
            result.update(acl_restored=restored,seconds=time.monotonic()-started)
            if not restored:result['passed']=False
            (work/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
            print(json.dumps(dict(passed=result['passed'],acl_restored=restored,evidence=str(work)),ensure_ascii=False),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
