export type ReviewDraft = {comment:string, handling:string, fingerprint:string, heads:string}

// Only investigation text/state is retained here, never an authoritative decision.
export class ReviewDrafts {
  private values = new Map<string, ReviewDraft>()
  key(scan:string, symbol:string) { return JSON.stringify([scan,symbol]) }
  get(scan:string, symbol:string) { return this.values.get(this.key(scan,symbol)) }
  update(scan:string, symbol:string, draft:ReviewDraft, savedHandling:string) {
    const key=this.key(scan,symbol)
    if(draft.comment || draft.handling!==savedHandling)this.values.set(key,{...draft})
    else this.values.delete(key)
  }
  remove(scan:string, symbol:string) { this.values.delete(this.key(scan,symbol)) }
  get size() { return this.values.size }
}
