// Text filters are live controls. Native `change` can be lost when a dialog
// removes the focused input, so debounce input and flush before closing it.
export function createFilterUpdates(apply: () => void, delay = 250) {
  let timer: ReturnType<typeof setTimeout> | undefined
  function cancel() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }
  function flush() {
    if (timer === undefined) return
    cancel()
    apply()
  }
  function schedule(event?: Event) {
    // Vue commits v-model only after composition finishes. Reading it during
    // IME input would query stale text and disable the field mid-composition.
    if (event && 'isComposing' in event && event.isComposing) return
    cancel()
    timer = setTimeout(flush, delay)
  }
  return { schedule, flush, cancel }
}
