"""Immutable, real engine-produced teaching archive; never synthetic findings."""
import hashlib
import json
from pathlib import Path
import tempfile

from ..report_package import import_report,sha256
from ..workspace import no_links

# Resolve the launcher's verified program alias before read-only asset lookup.
# Asset entries and every writable data path still pass through no_links.
ASSETS=Path(__file__).resolve().with_name('sample_assets')
EXPECTED_METADATA_SHA256='9126ffbc077bfbbd5396f4e1e444e4ab949f6ad8b13f4de03af917175a5ba9ba'
PROFILE_ID='builtin-stm32-demo'
TITLE='STM32并发访问教学示例'
NOTICE='教学示例 · 真实扫描归档 · 非用户工程。2个TU实际ARM对象编译/Clang分析，未链接固件、无硬件验证；未知与覆盖缺口按实保存。'


def sample_info(*,_assets=ASSETS):
    result=dict(available=False,title=TITLE,notice=NOTICE,profile_id=PROFILE_ID)
    try:
        metadata=no_links(Path(_assets)/'sample.json')
        if not metadata.is_file() or metadata.stat().st_size>65536:raise ValueError('缺少有效的内置示例清单')
        raw=metadata.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=EXPECTED_METADATA_SHA256:raise ValueError('内置示例清单摘要不符')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('内置示例清单必须为对象')
        package=no_links(Path(_assets)/'stm32-demo.ecra-report')
        if value.get('format')!='ECRA_BUILTIN_SAMPLE_V1' or value.get('filename')!=package.name:raise ValueError('内置示例版本或文件名不符')
        if type(value.get('bytes')) is not int or not package.is_file() or package.stat().st_size!=value['bytes'] or sha256(package)!=value.get('sha256'):
            raise ValueError('内置示例包缺失或摘要不符')
        result.update(available=True,scan_id=value['scan_id'],bytes=value['bytes'],sha256=value['sha256'])
    except (OSError,ValueError,KeyError) as exc:result['reason']=str(exc)+'；请保留当前数据，重新获取完整程序包。'
    return result


def open_sample(data_root,*,_assets=ASSETS):
    descriptor=sample_info(_assets=_assets)
    if not descriptor['available']:raise ValueError(descriptor['reason'])
    work=no_links(Path(data_root)/'work');work.mkdir(parents=True,exist_ok=True)
    # Freeze and verify bytes before the ordinary importer can publish anything.
    # A changed install asset never becomes a different, silently imported scan.
    with tempfile.TemporaryDirectory(prefix='builtin-sample-',dir=work) as folder:
        staged=Path(folder)/'sample.ecra-report';remaining=descriptor['bytes']
        source=no_links(Path(_assets)/'stm32-demo.ecra-report')
        with source.open('rb') as stream,staged.open('xb') as output:
            while remaining:
                block=stream.read(min(1024**2,remaining))
                if not block:raise ValueError('内置示例在复制期间缩短，请重新获取完整程序包')
                output.write(block);remaining-=len(block)
            if stream.read(1):raise ValueError('内置示例在复制期间变化，未导入')
        if sha256(staged)!=descriptor['sha256']:raise ValueError('内置示例在复制期间摘要变化，未导入')
        result=import_report(staged,data_root)
    return dict(**result,sample=descriptor)
