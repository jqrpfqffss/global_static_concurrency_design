export const riskCases: Record<string,string> = {
  R01:'安全结论保持', R02:'新增疑似风险', R03:'原安全依据不足',
  R04:'风险可能已消除', R05:'疑似风险持续', R06:'原风险尚不能关闭',
  R07:'当前取得安全证明', R08:'当前发现疑似风险，非确定新增', R09:'仍待核实',
}
export const objectEvents: Record<string,string> = {
  MATCHED:'同一对象', ADDED:'新增对象', DELETED:'已删除', ENTERED_BUILD:'进入当前构建',
  ABSENT_IN_BUILD:'当前构建未观察到', OUT_OF_BUILD:'移出当前构建',
  MATCH_UNCERTAIN:'对象匹配待核实', EXISTENCE_UNCERTAIN:'对象存在性待核实', STORAGE_SHAPE_CHANGED:'存储形态变化',
}
export function verificationLabel(state?:string) {
  return ({PASSED:'独立全量对照通过（当前侧）', NOT_RUN:'独立全量对照未执行',
    INCOMPLETE:'独立全量对照未完成（局部缺口）', FAILED:'独立全量对照失败'} as Record<string,string>)[state || ''] || '独立对照状态未记录'
}
export function publicationLabel(state?:string) {
  return ({COMPLETE:'完整覆盖结果已发布', VALID_PARTIAL:'有效局部结果已发布', FAILED:'本次失败'} as Record<string,string>)[state || ''] || '发布完整性未记录'
}
export function staticLabel(state?:string|null) {
  return ({SAFE_PROVEN:'静态安全', SUSPECT:'静态疑似', UNKNOWN:'静态未知', SHARED_NO_REVIEW:'共享无需复核', CONTAINER:'容器'} as Record<string,string>)[state || ''] || state || '未观察到（不表示删除）'
}
