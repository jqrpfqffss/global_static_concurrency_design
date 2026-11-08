"""One bounded display contract for catalogs, details and import merge targets.

Display metadata never upgrades an offline binding to current-source proof.
"""
import json

from ..workspace import no_links


DISPLAY_MANIFEST_LIMIT = 4*1024*1024  # same maximum as accepted result packages


def manifest_object(raw, stage):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(stage+'：清单 JSON 无效；原文件和已有数据保留。请从完整备份恢复或重新生成结果。技术信息：'+str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError(stage+'：清单必须是 JSON 对象；原文件和已有数据保留。请从完整备份恢复或重新生成结果。技术类型：'+type(value).__name__)
    return value


def display_manifest(path, binding):
    path = no_links(path)
    stage = '读取扫描显示清单 '+str(path)
    with path.open('rb') as stream:
        raw = stream.read(DISPLAY_MANIFEST_LIMIT+1)
    if len(raw)>DISPLAY_MANIFEST_LIMIT:
        raise ValueError(stage+'：清单超过4MiB预算；原件保留，请核对完整结果包或重新扫描。')
    value = manifest_object(raw, stage)
    if not isinstance(value.get('format'),str) or value['format'] not in {'ECRA_LOCAL_SCAN','ECRA_REPORT','ECRA_LEGACY_IMPORT'}:
        raise ValueError(stage+'：清单格式不受当前版本支持；请保留原件并使用匹配版本或完整备份恢复。')
    if 'version' in value and (type(value['version']) is not int or value['version']!=1):
        raise ValueError(stage+'：清单版本无效；请保留原件并使用匹配版本或完整备份恢复。')
    if any(value.get(key)!=binding[key] for key in ('scan_id','project_id','facts_hash','report_hash')):
        raise ValueError(stage+'：清单与静态库的工程、扫描或证据摘要不一致；不能采用此显示状态。请保留原件并从完整备份恢复。')
    # Native and derived publishers finalize with STATIC_VALIDATED while the
    # immutable DB retains UNVERIFIED. run_state is a separate contract.
    # Portable reports establish no local state; their reader uses the DB.
    if value['format']=='ECRA_LOCAL_SCAN' and value.get('state')!='STATIC_VALIDATED':
        raise ValueError(stage+'：发布状态不符合当前本机发布协议，不能采用此显示状态。原件保留，请核对完整备份或重新扫描。')
    # Legacy conversion publishes complete old facts as LEGACY_READ_ONLY and
    # opaque originals as UNVERIFIED. Neither proves current source validity.
    if value['format']=='ECRA_LEGACY_IMPORT' and (
            binding['state'] not in {'LEGACY_READ_ONLY','UNVERIFIED'} or value.get('state')!=binding['state']):
        raise ValueError(stage+'：旧归档发布状态与静态库限制不一致，不能采用此显示状态。原件保留，请核对完整备份。')
    return value
