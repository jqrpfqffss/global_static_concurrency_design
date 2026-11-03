"""Real kernel ENOSPC validation; invoke through validate_disk_full_volume.ps1.

Never use a host/firmware volume. The driver creates and verifies a new 256MiB
file-backed NTFS volume and always detaches it. All images/evidence are retained.
"""
import argparse
from contextlib import closing
import errno,json,os,re,shutil,sqlite3,sys,time,traceback,urllib.request
from pathlib import Path

def main():
 p=argparse.ArgumentParser()
 for name in ['volume','work','evidence']:p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--engine',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--python',type=Path)
 args=p.parse_args();engine=args.engine.resolve(strict=True);runtime=(args.python or engine/'runtime/python.exe').resolve(strict=True);sys.path.insert(0,str(engine))
 from ecra.workspace import no_links,studio_data_root
 from ecra.report_package import import_report,export_report,sha256
 from ecra.scan_store import EvidenceProvider
 from ecra.human_reviews import ReviewStore
 from ecra.studio.process_budget import ProcessBudget
 from ecra.studio.write_guard import OwnedProcess
 volume=json.loads(args.volume.read_text('utf-8-sig'));owned=no_links(volume['owned_root']);data=studio_data_root(volume['data_root'])
 assert volume['filesystem']=='NTFS' and 240*1024**2<=volume['total_bytes']<=258*1024**2
 assert no_links(volume['marker']).read_text('utf-8')==volume['nonce'] and data.is_relative_to(owned)
 assert Path(volume['filler']).parent==owned and Path(volume['filler']).name=='filler.bin'
 assert owned.anchor.upper() not in {path.resolve().anchor.upper() for path in [engine,args.package,args.work,args.evidence,runtime]}
 assert 240*1024**2<=shutil.disk_usage(owned).total<=258*1024**2
 work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False);output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False)
 (work/'controller.py').write_bytes(Path(__file__).read_bytes())
 result=dict(passed=False,scope='Actual Windows kernel disk-full on new owned256MiB VHD NTFS; real GUI writes/export and recovery. Not physical host disk-full, power loss, whole G5/G4/32GB/second-PC/DPI/UAT.',tests=[],screenshots=[],page_errors=[],phase='PREPARING',volume=volume,engine=str(engine),runtime=str(runtime),runtime_sha256=sha256(runtime),package=str(args.package),controller_sha256=sha256(Path(__file__)))
 def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
 def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
 code_files=[path for path in (engine/'ecra').rglob('*') if path.is_file() and path.suffix in {'.py','.js','.css','.html'}]
 code_before={str(path.relative_to(engine)):sha256(path) for path in code_files}
 result['runtime_code_files']=len(code_before);save();budget=process=log=playwright=browser=context=filler=page=sharing=None
 try:
  package=no_links(args.package);package_before=sha256(package)
  imported=import_report(package,data);scan=data/'scans'/imported['scan_id'];provider=EvidenceProvider(scan/'scan.db');binding=provider.metadata();store=ReviewStore(scan/'reviews.db',binding)
  symbol=next(row['symbol_id'] for row in provider.symbols(limit=200)['items'] if not store.current(row['symbol_id'],provider.fingerprint(row['symbol_id']))['heads'])
  store.append(symbol,provider.fingerprint(symbol),decision='NEED_MORE_EVIDENCE',reviewer='容量故障验收（用户声明）',comment='容量测试前保留的证据不足记录，不作硬件风险判定。')
  before_events=store.history();static_before=sha256(scan/'scan.db');exports=data/'exports';exports.mkdir();old=exports/('f'*32+'.ecra-report');export_report(scan,old);old_sha=sha256(old)
  result.update(symbol_id=symbol,events_before=len(before_events),static_sha256_before=static_before,old_export_sha256=old_sha)
  session=work/'session.json';log=(work/'server.log').open('xb');budget=ProcessBudget(2*1024**3)
  process=OwnedProcess([str(runtime),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)],cwd=engine,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),log=log)
  budget.assign(process);process.resume();deadline=time.monotonic()+60
  while not session.is_file():
   if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Actual service did not start')
   time.sleep(.1)
  info=json.loads(session.read_text('utf-8'));origin='http://'+info['authority']
  while True:
   try:
    urllib.request.urlopen(urllib.request.Request(origin+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=2).close();break
   except OSError:
    if time.monotonic()>deadline:raise
    time.sleep(.1)
  from playwright.sync_api import sync_playwright,expect
  playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True);context=browser.new_context(viewport=dict(width=1600,height=900),accept_downloads=True)
  context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page();page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
  def shot(tab,name):
   file=output/(name+'.png');tab.screenshot(path=str(file),full_page=True);result['screenshots'].append(str(file));save()
  page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=120000);page.get_by_role('link',name='变量与风险',exact=True).click()
  search=page.get_by_label('查找变量、文件或规范身份',exact=True);search.fill(symbol);search.press('Enter');expect(page.locator('.symbol')).to_have_count(1,timeout=120000);page.locator('.symbol').click()
  expect(page.locator('.detail-summary')).to_contain_text('暂无法确认',timeout=120000)
  sharing=context.new_page();sharing.goto(info['url']);expect(sharing.locator('.activity')).to_have_count(0,timeout=120000);sharing.get_by_role('link',name='数据与共享',exact=True).click();expect(sharing.locator('.activity')).to_have_count(0,timeout=120000)
  result['phase']='FILLING_ONLY_OWNED_VIRTUAL_VOLUME';save();filler=open(no_links(volume['filler']),'xb',buffering=0);block=b'\0'*(1024**2);failure=None
  try:
   while shutil.disk_usage(owned).free>2*1024**2:filler.write(block)
   while True:filler.write(block[:4096])
  except OSError as error:
   failure=dict(errno=error.errno,winerror=getattr(error,'winerror',None),message=str(error));assert error.errno==errno.ENOSPC or getattr(error,'winerror',None) in {39,112}
  filler.flush();os.fsync(filler.fileno());result.update(kernel_full_error=failure,free_bytes_when_full=shutil.disk_usage(owned).free,filler_bytes=os.fstat(filler.fileno()).st_size)
  assert failure and result['free_bytes_when_full']<=65536;passed('actual_new_ntfs_volume_reaches_kernel_disk_full_without_filling_host_or_firmware_volume')
  page.get_by_label('确认者',exact=True).fill('容量故障验收（用户声明）');page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('此提交必须因真实卷已满而失败；不应出现保存成功。')
  page.get_by_role('button',name='确认有风险',exact=True).click();alert=page.get_by_role('alert').filter(has_text=re.compile('full|空间|磁盘|不足',re.I)).first;expect(alert).to_be_visible(timeout=30000)
  result['review_full_message']=alert.inner_text();expect(page.locator('.detail-summary')).to_contain_text('暂无法确认')
  with closing(sqlite3.connect((scan/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
   actual=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM events ORDER BY revision,event_id')]
  assert actual==before_events;shot(page,'01-real-full-confirmation-not-saved');passed('real_gui_sqlite_full_rejects_confirmation_and_preserves_every_old_event_and_displayed_decision')
  sharing.get_by_role('button',name='导出标准完整包',exact=True).click();alert=sharing.get_by_role('alert').filter(has_text=re.compile('full|空间|磁盘|不足',re.I)).first;expect(alert).to_be_visible(timeout=30000)
  result['export_full_message']=alert.inner_text();assert list(exports.glob('*.ecra-report'))==[old] and sha256(old)==old_sha and sha256(scan/'scan.db')==static_before
  shot(sharing,'02-real-full-export-keeps-last-valid-package');passed('real_gui_export_disk_full_never_publishes_partial_final_package_or_replaces_old_authority')
  filler.truncate(0);filler.flush();os.fsync(filler.fileno());filler.close();filler=None;result['free_bytes_after_recovery']=shutil.disk_usage(owned).free
  provider.validate(deep=True);assert store.history()==before_events and sha256(old)==old_sha
  page.get_by_role('button',name='确认有风险',exact=True).click();expect(page.locator('.detail-summary')).to_contain_text('人工确认有风险',timeout=120000)
  assert len(store.history())==len(before_events)+1;assert all(event in store.history() for event in before_events)
  with sharing.expect_download(timeout=120000) as operation:sharing.get_by_role('button',name='导出标准完整包',exact=True).click()
  downloaded=operation.value;recovered=work/'recovered.ecra-report';downloaded.save_as(recovered);assert downloaded.failure() is None
  restored=import_report(recovered,work/'independent-restored');restored_scan=work/'independent-restored/scans'/restored['scan_id']
  assert EvidenceProvider(restored_scan/'scan.db').metadata()==binding and ReviewStore(restored_scan/'reviews.db',binding).history()==store.history()
  assert sha256(scan/'scan.db')==static_before and sha256(package)==package_before
  shot(page,'03-space-recovered-real-confirmation-saves');shot(sharing,'04-space-recovered-full-package-roundtrip');passed('after_releasing_only_own_filler_same_gui_saves_new_event_and_exports_strictly_importable_full_archive')
  actionable=all('空间' in result[key] and ('重试' in result[key] or '释放' in result[key]) for key in ['review_full_message','export_full_message'])
  result.update(messages_actionable_chinese=actionable,static_sha256_after=sha256(scan/'scan.db'),events_after_recovery=len(store.history()),source_package_unchanged=sha256(package)==package_before,phase='COMPLETE')
  if not actionable:result['usability_failure']='Actual disk-full errors lack Chinese cause and concrete recovery action; integrity passes do not close professional UI gate.'
  code_after={str(path.relative_to(engine)):sha256(path) for path in code_files}
  result['runtime_code_differences']=[name for name,digest in code_before.items() if code_after.get(name)!=digest]
  result['passed']=len(result['tests'])==4 and actionable and not result['page_errors'] and not result['runtime_code_differences'];save();return 0 if result['passed'] else 1
 except BaseException:
  result.update(error=traceback.format_exc(),phase='FAILED')
  if page:
   try:shot(page,'failed')
   except Exception:pass
  save();raise
 finally:
  if filler:
   try:filler.truncate(0);filler.flush();os.fsync(filler.fileno())
   finally:filler.close()
  if context:
   try:context.tracing.stop(path=str(output/'browser-trace.zip'))
   except Exception:pass
   context.close()
  if browser:browser.close()
  if playwright:playwright.stop()
  if budget:budget.close()
  if process:process.wait(timeout=30);process.close()
  if log:log.close()

if __name__=='__main__':raise SystemExit(main())
