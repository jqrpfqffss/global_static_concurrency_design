import test from 'node:test'
import assert from 'node:assert/strict'
import {riskCases, objectEvents, staticLabel, verificationLabel, publicationLabel} from '../src/diffPresentation.ts'

test('all nine static transitions and shared exemption keep separate meanings',()=>{
  assert.equal(Object.keys(riskCases).length,9)
  assert.match(riskCases.R08,/非确定新增/)
  assert.match(riskCases.R06,/不能关闭/)
  assert.notEqual(staticLabel('SHARED_NO_REVIEW'),staticLabel('SAFE_PROVEN'))
  assert.match(staticLabel(null),/不表示删除/)
  assert.notEqual(objectEvents.EXISTENCE_UNCERTAIN,objectEvents.DELETED)
})
test('partial publication and independent verification are separate statuses',()=>{
  assert.match(publicationLabel('VALID_PARTIAL'),/有效局部/)
  assert.match(verificationLabel('INCOMPLETE'),/未完成/)
  assert.match(verificationLabel('NOT_RUN'),/未执行/)
  assert.match(verificationLabel(undefined),/未记录/)
  assert.match(verificationLabel('PASSED'),/通过/)
})
