import test from 'node:test'
import assert from 'node:assert/strict'
import { createFilterUpdates } from '../src/filterUpdates.ts'

test('text filter uses the latest input after typing stops, without a change event', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let text = 'oth', calls = []
  const updates = createFilterUpdates(() => calls.push(text))
  updates.schedule()
  t.mock.timers.tick(200)
  text = 'other.c'
  updates.schedule()
  t.mock.timers.tick(249)
  assert.deepEqual(calls, [])
  t.mock.timers.tick(1)
  assert.deepEqual(calls, ['other.c'])
})

test('closing the filter dialog before debounce applies its last input once', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const calls = [], updates = createFilterUpdates(() => calls.push('other.c'))
  updates.schedule()
  updates.flush()
  assert.deepEqual(calls, ['other.c'])
  t.mock.timers.tick(1000)
  updates.flush()
  assert.deepEqual(calls, ['other.c'])
})

test('immediate filters or a scan/page change cancel the obsolete pending read', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let reads = 0
  const updates = createFilterUpdates(() => reads++)
  updates.schedule()
  updates.cancel()
  t.mock.timers.tick(1000)
  updates.flush()
  assert.equal(reads, 0)
})

test('IME composition keeps the field editable and queries only committed text', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const calls = [], updates = createFilterUpdates(() => calls.push('中文路径'))
  updates.schedule()
  t.mock.timers.tick(100)
  updates.cancel() // compositionstart cancels a pending pre-composition query.
  updates.schedule({ isComposing: true })
  t.mock.timers.tick(1000)
  assert.deepEqual(calls, [])
  updates.schedule({ isComposing: false }) // Vue's committed input event.
  t.mock.timers.tick(250)
  assert.deepEqual(calls, ['中文路径'])
})
