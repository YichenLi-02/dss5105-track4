// Same-origin fetch wrapper: session cookie (HttpOnly) + CSRF header on every mutation.
// No model key or OAuth token ever reaches the browser.

export class ApiError extends Error {
  status: number
  code: string
  details: string[]
  constructor(status: number, code: string, message: string, details: string[] = []) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let csrf: string | null = null
let sessionPromise: Promise<void> | null = null

async function ensureSession(force = false): Promise<void> {
  if (csrf && !force) return
  if (!sessionPromise || force) {
    sessionPromise = (async () => {
      const r = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bootstrap_code: sessionStorage.getItem('swa_bootstrap') || null }),
        credentials: 'same-origin',
      })
      if (!r.ok) throw await toError(r)
      csrf = (await r.json()).csrf_token
    })().finally(() => {
      sessionPromise = null
    })
  }
  return sessionPromise
}

async function toError(r: Response): Promise<ApiError> {
  try {
    const body = await r.json()
    const e = body.error || {}
    return new ApiError(r.status, e.code || 'HTTP_' + r.status, e.message || r.statusText, e.details || [])
  } catch {
    return new ApiError(r.status, 'HTTP_' + r.status, r.statusText)
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string>; signal?: AbortSignal }

export async function api<T = any>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  await ensureSession()
  const method = opts.method || 'GET'
  const headers: Record<string, string> = { ...(opts.headers || {}) }
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf || ''
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const r = await fetch(path, { method, headers, body, credentials: 'same-origin', signal: opts.signal })
  if (r.status === 401 && !retried) {
    // Server restarted -> in-memory session gone. Re-create once, then retry.
    await ensureSession(true)
    return api<T>(path, opts, true)
  }
  if (!r.ok) throw await toError(r)
  if (r.status === 204) return undefined as T
  return r.json()
}

export const get = <T = any>(p: string, signal?: AbortSignal) => api<T>(p, { signal })
export const post = <T = any>(p: string, body?: unknown, headers?: Record<string, string>) =>
  api<T>(p, { method: 'POST', body: body ?? {}, headers })
export const patch = <T = any>(p: string, body: unknown) => api<T>(p, { method: 'PATCH', body })
export const del = <T = any>(p: string, body: unknown) => api<T>(p, { method: 'DELETE', body })
export const upload = <T = any>(p: string, form: FormData) => api<T>(p, { method: 'POST', form })

export async function waitJob(id: string, onTick?: (job: any) => void): Promise<any> {
  for (;;) {
    const job = await get(`/api/jobs/${id}`)
    onTick?.(job)
    if (!['queued', 'running'].includes(job.status)) return job
    await new Promise((res) => setTimeout(res, 1000))
  }
}
