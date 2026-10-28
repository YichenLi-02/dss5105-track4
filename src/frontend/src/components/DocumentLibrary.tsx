// Course documents. The backend parses real PDF text with page numbers; scans, encrypted and broken
// files are reported as such and the user can paste the original text instead.
import { useEffect, useRef, useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
import { del, get, patch, post, upload } from '../api/client'
import type { DocumentRec } from '../api/types'
import { useApp } from '../app/context'
import { pick as pickLabel, useI18n } from '../app/i18n'
import { deadlineText, TaskDetail } from '../pages/TasksPage'
import { StatusTag } from './Tags'

const MAX = 20 * 1024 * 1024

export function DocumentLibrary() {
  const { t, locale } = useI18n()
  const app = useApp()
  const [docs, setDocs] = useState<DocumentRec[] | null>(null)
  const [form, setForm] = useState({ kind: 'syllabus', course: '', term: '', source_timezone: app.prefs?.display_timezone || 'Asia/Singapore',
    title: '', page: '', excerpt: '', permission: false })
  const [file, setFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [fileNote, setFileNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const reload = () => get<DocumentRec[]>('/api/documents').then(setDocs).catch((e) => setErr(e.message))
  useEffect(() => { reload() }, [app.dataVersion])

  async function pick(f: File | null) {
    setFileNote(null)
    setFile(null)
    if (!f) return
    if (f.size > MAX) return setFileNote(t('docs.too_large'))
    const head = new TextDecoder().decode(await f.slice(0, 5).arrayBuffer())
    if (head !== '%PDF-') return setFileNote(t('docs.not_pdf'))
    setFile(f)
    setFileNote(t('docs.file_selected', { name: f.name, kb: Math.round(f.size / 1024) }))
  }

  async function add() {
    setBusy(true); setErr(null)
    try {
      let upload_id: string | null = null
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('format', 'pdf')
        upload_id = (await upload('/api/uploads', fd)).upload_id
      }
      const d = await post<DocumentRec>('/api/documents', {
        upload_id, kind: form.kind, course: form.course || null, term: form.term, source_timezone: form.source_timezone,
        title: form.title || null, user_excerpt: form.excerpt || null, user_excerpt_page: form.page ? Number(form.page) : null,
        permission_confirmed: form.permission,
      })
      app.toast(t('docs.status_toast.' + d.extraction_status, { pages: d.page_count }))
      setForm({ ...form, title: '', page: '', excerpt: '' })
      setFile(null); setFileNote(null)
      reload()
    } catch (e: any) {
      setErr(t('docs.error.' + e.code) !== 'docs.error.' + e.code ? t('docs.error.' + e.code) : e.message)
    } finally {
      setBusy(false)
    }
  }

  async function extract(d: DocumentRec) {
    try {
      const calendars = (docs || []).filter((x) => x.kind === 'academic_calendar' && !x.excluded).map((x) => x.id)
      const r = await post(`/api/documents/${d.id}/extract`, { expected_revision: d.revision, calendar_document_ids: calendars, use_model: false })
      app.toast(d.kind === 'academic_calendar' ? t('docs.calendar_facts', { rw: r.result.calendar_facts?.reading_week?.join(' – ') || '—' })
        : t('docs.extracted', { n: r.result.candidates }))
      reload(); app.bump()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function toggleExclude(d: DocumentRec) {
    await patch(`/api/documents/${d.id}`, { expected_revision: d.revision, excluded: !d.excluded })
    app.toast(t(d.excluded ? 'docs.included' : 'docs.excluded_toast'))
    reload(); app.bump()
  }

  async function remove(d: DocumentRec) {
    const r = await del(`/api/documents/${d.id}`, { expected_revision: d.revision })
    app.toast(t('docs.deleted', { n: r.affected_tasks }))
    reload(); app.bump()
  }

  async function loadDemo() {
    const r = await post<DocumentRec[]>('/api/demo/documents')
    app.toast(r.length ? t('docs.demo_loaded') : t('docs.demo_exists'))
    reload()
  }

  const set = (k: string, v: any) => setForm({ ...form, [k]: v })
  const canAdd = form.permission && form.term.trim() && (file || form.excerpt.trim())

  return (
    <>
      <div className="banner">{t('docs.banner')}</div>
      <div className="grid2" id="source-documents">
        <div className="box">
          <h2>{t('docs.add')}</h2>
          <div className="fields">
            <div className="field"><label htmlFor="doc-kind">{t('docs.kind')}</label>
              <select id="doc-kind" value={form.kind} onChange={(e) => set('kind', e.target.value)}>
                {['syllabus', 'assignment_brief', 'academic_calendar'].map((k) => <option key={k} value={k}>{t('kind.' + k)}</option>)}
              </select></div>
            <div className="field"><label htmlFor="doc-course">{t('docs.course')}</label><input id="doc-course" value={form.course} onChange={(e) => set('course', e.target.value)} /></div>
            <div className="field"><label htmlFor="doc-term">{t('docs.term')} *</label><input id="doc-term" value={form.term} onChange={(e) => set('term', e.target.value)} /></div>
            <div className="field"><label htmlFor="doc-tz">{t('docs.timezone')}</label><input id="doc-tz" value={form.source_timezone} onChange={(e) => set('source_timezone', e.target.value)} /></div>
          </div>
          <div className="field">
            <label htmlFor="doc-file">{t('docs.file')}</label>
            <input id="doc-file" ref={fileInput} className="sr-only" tabIndex={-1} type="file" accept="application/pdf,.pdf"
              onChange={(e) => { pick(e.target.files?.[0] || null); e.target.value = '' }} />
            <div className="row">
              <button type="button" onClick={() => fileInput.current?.click()}>{t('docs.choose_file')}</button>
              <small>{fileNote ?? t('docs.no_file_chosen')}</small>
            </div>
          </div>
          <div className="fields">
            <div className="field"><label htmlFor="doc-title">{t('docs.title_f')}</label><input id="doc-title" value={form.title} onChange={(e) => set('title', e.target.value)} /></div>
            <div className="field"><label htmlFor="doc-page">{t('docs.page')}</label><input id="doc-page" type="number" min={1} value={form.page} onChange={(e) => set('page', e.target.value)} placeholder={t('docs.page_ph')} /></div>
          </div>
          <div className="field">
            <label htmlFor="doc-ex">{t('docs.excerpt')}</label>
            <textarea id="doc-ex" rows={6} value={form.excerpt} onChange={(e) => set('excerpt', e.target.value)} placeholder={t('docs.excerpt_ph')} />
            <small>{t('docs.excerpt_hint')}</small>
          </div>
          <label className="checkline"><input type="checkbox" checked={form.permission} onChange={(e) => set('permission', e.target.checked)} />{t('docs.permission')}</label>
          {err && <div className="banner red" role="alert">{err}</div>}
          <div className="row">
            <button className="primary" disabled={!canAdd || busy} onClick={add}>{t(busy ? 'docs.adding' : 'docs.add_btn')}</button>
            {app.prefs?.show_demo_data_effective && <button onClick={loadDemo}>{t('docs.load_demo')}</button>}
          </div>
        </div>
        <div>
          <div className="box">
            <div className="row between"><h2>{t('docs.list')}</h2><span className="tag">{docs?.length ?? 0}</span></div>
            {docs && docs.length === 0 && <p className="footnote">{t('docs.empty')}</p>}
            {docs?.map((d) => (
              <div key={d.id} className="decision">
                <div className="row between">
                  <b>{pickLabel(locale, d.title, d.title_en)}</b>
                  <span className="row" style={{ gap: 4 }}>
                    <span className={`tag ${['failed', 'encrypted', 'needs_ocr'].includes(d.extraction_status) ? 'red' : d.extraction_status === 'text_ready' || d.extraction_status === 'complete' ? 'green' : 'warn'}`}>
                      {t('docs.status.' + d.extraction_status)}</span>
                    {d.synthetic && <span className="tag warn">{t('common.synthetic')}</span>}
                    {d.excluded && <span className="tag red">{t('docs.excluded')}</span>}
                  </span>
                </div>
                <small className="footnote">
                  {t('kind.' + d.kind)} · {d.course || t('docs.all_courses')} · {d.term} · {d.source_timezone}<br />
                  {d.filename ? `${d.filename} · ${d.page_count} ${t('docs.pages')}` : t('docs.no_file')}
                  {d.user_excerpt ? ` · ${t('docs.has_excerpt')}` : ''}
                  {d.extraction_error ? ` · ${d.extraction_error}` : ''}
                </small>
                <div className="mail-footer">
                  <button className="link" onClick={() => app.openPanel(d.title, () => <DocumentView id={d.id} />)}>{t('docs.view')}</button>
                  <button className="link" disabled={d.excluded || (!d.user_excerpt && !['text_ready', 'complete'].includes(d.extraction_status))} onClick={() => extract(d)}>
                    {t(d.kind === 'academic_calendar' ? 'docs.read_calendar' : 'docs.extract')}</button>
                  <button className="link" onClick={() => toggleExclude(d)}>{t(d.excluded ? 'docs.include' : 'docs.exclude')}</button>
                  <ConfirmButton className="link" label={t('docs.delete')} message={t('docs.delete_confirm', { title: d.title, n: d.candidates.length })}
                    onConfirm={() => remove(d)} />
                </div>
              </div>
            ))}
          </div>
          <div className="box">
            <h2>{t('docs.candidates')}</h2>
            <p className="footnote">{t('docs.candidates_hint')}</p>
            {docs?.flatMap((d) => d.candidates.map((c) => (
              <div key={c.id} className="decision">
                <b>{pickLabel(locale, c.title, c.title_en)}</b> <StatusTag status={c.status} /> <span className="tag">{t('deadline.' + c.deadline_status)}</span><br />
                <small>{deadlineText(t, c)} · {pickLabel(locale, d.title, d.title_en)}</small>
                <div className="source-quote">{c.evidence[0]?.quote}</div>
                <button className="link" onClick={() => app.openPanel(c.title, () => <TaskDetail id={c.id} />)}>{t('task.check')}</button>
              </div>
            )))}
          </div>
        </div>
      </div>
    </>
  )
}

function DocumentView({ id }: { id: string }) {
  const { t } = useI18n()
  const app = useApp()
  const [d, setD] = useState<DocumentRec | null>(null)
  const [excerpt, setExcerpt] = useState('')
  const [page, setPage] = useState('')
  useEffect(() => {
    get<DocumentRec>(`/api/documents/${id}`).then((x) => { setD(x); setExcerpt(x.user_excerpt); setPage(x.user_excerpt_page ? String(x.user_excerpt_page) : '') })
  }, [id])
  if (!d) return <p>{t('common.loading')}</p>
  async function saveExcerpt() {
    const x = await patch<DocumentRec>(`/api/documents/${id}`, { expected_revision: d!.revision, user_excerpt: excerpt, page: page ? Number(page) : null })
    setD(x)
    app.toast(t('docs.excerpt_saved'))
    app.bump()
  }
  return (
    <>
      <dl className="kv">
        <dt>{t('docs.status_label')}</dt><dd>{t('docs.status.' + d.extraction_status)}{d.extraction_error ? ` — ${d.extraction_error}` : ''}</dd>
        <dt>{t('docs.file')}</dt><dd>{d.filename || t('docs.no_file')} {d.size_bytes ? `· ${Math.round(d.size_bytes / 1024)} KB` : ''}</dd>
        <dt>{t('docs.pages')}</dt><dd>{d.pages.map((p) => `p${p.page}: ${p.chars}`).join(' · ') || '—'}</dd>
      </dl>
      {['needs_ocr', 'encrypted', 'failed', 'metadata_only'].includes(d.extraction_status) && <div className="banner warning">{t('docs.paste_fallback')}</div>}
      {d.parsed_text && (<><h3>{t('docs.parsed_text')}</h3><pre>{d.parsed_text}</pre></>)}
      <h3>{t('docs.user_excerpt')}</h3>
      <p className="footnote">{t('docs.user_excerpt_note')}</p>
      <div className="field"><textarea rows={6} value={excerpt} onChange={(e) => setExcerpt(e.target.value)} aria-label={t('docs.user_excerpt')} /></div>
      <div className="field"><label htmlFor="dv-page">{t('docs.page')}</label><input id="dv-page" type="number" min={1} value={page} onChange={(e) => setPage(e.target.value)} /></div>
      <div className="panel-actions"><button className="primary" onClick={saveExcerpt}>{t('docs.save_excerpt')}</button></div>
    </>
  )
}
