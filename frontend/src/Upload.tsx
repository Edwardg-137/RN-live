import { useState, type FormEvent } from 'react'
import { api } from './api'
import { kinds, type Kind, type Recording } from './types'

export function Upload({onCreated}:{onCreated:(recording:Recording)=>void}) {
  const [kind,setKind] = useState<Kind>('speech')
  const [count,setCount] = useState(1)
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    if (!data.get('content_date')) data.delete('content_date')
    const file = data.get('file') as File
    if (!file.size || file.size > 1_000_000_000) {setError('Elige un archivo de hasta 1 GB.'); return}
    setBusy(true); setError('')
    try {onCreated(await api<Recording>('/recordings', {method:'POST', body:data}))}
    catch (error) {setError((error as Error).message)}
    finally {setBusy(false)}
  }
  return <section className="upload panel">
    <p className="eyebrow">TU BIBLIOTECA</p><h1>Nueva grabación</h1>
    <p className="muted">Prepara un discurso, debate o entrevista para revisar lo que se dijo, voz por voz.</p>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <label className="filebox">Archivo de audio o video<input required name="file" type="file" accept=".wav,.mp3,.mp4"/><small>MP4 H.264/AAC, MP3 o WAV · hasta 60 minutos y 1 GB</small></label>
        <label>Título<input required maxLength={200} name="title" placeholder="Ej. Entrevista sobre transporte"/></label>
        <div className="form-grid">
          <label>Tipo de contenido<select name="kind" value={kind} onChange={e=>{const next=e.target.value as Kind; setKind(next); setCount(next==='speech'?1:2)}}>{Object.entries(kinds).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
          <label>Voces principales<select name="speaker_count" value={count} onChange={e=>setCount(Number(e.target.value))}>{[1,2,3,4].map(n=><option key={n}>{n}</option>)}</select></label>
          <label>Fecha de la grabación (opcional)<input name="content_date" type="date"/></label>
          <label>País o ámbito (opcional)<input name="scope" maxLength={200} placeholder="Ej. Guatemala"/></label>
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        <button className="primary" type="submit">{busy?'Subiendo y validando…':'Crear grabación'}</button>
      </fieldset>
    </form>
  </section>
}
