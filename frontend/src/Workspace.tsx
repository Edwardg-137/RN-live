import { useEffect, useRef, useState } from 'react'
import { api, json } from './api'
import { ClaimsPanel } from './ClaimsPanel'
import { activeSegments, formatTime, splitSegment } from './timeline'
import { kinds, statuses, type Recording, type Segment, type Speaker, type Transcript, type Snapshot, type Claim, type ClaimCategory, type ClaimRun } from './types'
import './workspace.css'

export function Workspace({id,onChange,onDeleted,onDirty}:{id:string;onChange:()=>void;onDeleted:()=>void;onDirty:(dirty:boolean)=>void}) {
  const [record,setRecord] = useState<Recording|null>(null)
  const [transcript,setTranscript] = useState<Transcript>({revision:0,segments:[]})
  const [speakers,setSpeakers] = useState<Speaker[]>([])
  const [speakerDirty,setSpeakerDirty] = useState(false)
  const [transcriptDirty,setTranscriptDirty] = useState(false)
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [notice,setNotice] = useState('')
  const [time,setTime] = useState(0)
  const [follow,setFollow] = useState(true)
  const [claimRun,setClaimRun] = useState<ClaimRun|null>(null)
  const [claimDirty,setClaimDirty] = useState(false)
  const [editor,setEditor] = useState<'speakers'|'transcript'|null>(null)
  const player = useRef<HTMLVideoElement>(null)
  const speakerButton = useRef<HTMLButtonElement>(null)
  const transcriptButton = useRef<HTMLButtonElement>(null)
  const rows = useRef<(HTMLElement|null)[]>([])
  const cursors = useRef<Record<number,number>>({})
  const path = `/recordings/${id}`
  const processing = record?.status === 'queued' || record?.status === 'transcribing'
  const dirty = speakerDirty||transcriptDirty
  const active = activeSegments(transcript.segments,time)
  const activeKey = active.join(',')

  async function load() {
    const item = await api<Snapshot>(path)
    setRecord(item); setSpeakers(item.speakers); setTranscript({revision:item.revision,segments:item.segments}); api<ClaimRun>(path+'/claim-extraction').then(setClaimRun).catch(()=>setClaimRun(null))
  }
  async function refreshClaimRun(){try{setClaimRun(await api<ClaimRun>(path+'/claim-extraction'))}catch{setClaimRun(null)}}
  useEffect(()=>{let cancelled=false; api<Snapshot>(path).then(item=>{if(!cancelled){setRecord(item);setSpeakers(item.speakers);setTranscript({revision:item.revision,segments:item.segments}); api<ClaimRun>(path+'/claim-extraction').then(run=>{if(!cancelled)setClaimRun(run)}).catch(()=>{})}}).catch(e=>{if(!cancelled)setError(e.message)}); return()=>{cancelled=true}},[path])
  useEffect(()=>{const unsaved=dirty||claimDirty;onDirty(unsaved); const warn=(e:BeforeUnloadEvent)=>{if(unsaved)e.preventDefault()}; window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty,claimDirty,onDirty])
  useEffect(()=>{
    if(!processing)return
    let stopped=false
    const timer=window.setInterval(async()=>{try{const item=await api<Snapshot>(path);if(stopped)return;setRecord(item);if(!['queued','transcribing'].includes(item.status)){setSpeakers(item.speakers);setTranscript({revision:item.revision,segments:item.segments});await refreshClaimRun();onChange()}}catch(e){if(!stopped)setError((e as Error).message)}},2000)
    return()=>{stopped=true;window.clearInterval(timer)}
  },[processing,path])
  useEffect(()=>{if(follow&&editor==='transcript'&&active.length)rows.current[active[0]]?.scrollIntoView({block:'nearest',behavior:'smooth'})},[activeKey,follow,editor])
  useEffect(()=>{if(!record || !['queued','running'].includes(claimRun?.status||''))return; const timer=window.setInterval(()=>api<ClaimRun>(path+'/claim-extraction').then(setClaimRun).catch(()=>{}),2000); return()=>window.clearInterval(timer)},[record,claimRun?.status,path])
  useEffect(()=>{if(!editor)return;const close=(event:KeyboardEvent)=>{if(event.key==='Escape')closeEditor()};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close)},[editor])

  function closeEditor(){const button=editor==='speakers'?speakerButton.current:transcriptButton.current;setEditor(null);requestAnimationFrame(()=>button?.focus())}
  function changeSegment(index:number,change:Partial<Segment>){setTranscript(value=>({...value,segments:value.segments.map((s,i)=>i===index?{...s,...change}:s)}));setTranscriptDirty(true)}
  async function action(name:string){setBusy(true);setError('');setNotice('');try{await api(path+'/'+name,{method:'POST'});await load();onChange()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function save(){setBusy(true);setError('');setNotice('');try{const saved=await api<{revision:number}>(path+'/speakers',json('PUT',{revision:transcript.revision,speakers}));setTranscript(value=>({...value,revision:saved.revision}));const result=await api<Transcript>(path+'/segments',json('PUT',{...transcript,revision:saved.revision}));setTranscript(result);await refreshClaimRun();setSpeakerDirty(false);setTranscriptDirty(false);setNotice('Revisión guardada.');onChange()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  function split(index:number){try{const parts=splitSegment(transcript.segments[index],Math.round(time*1000),cursors.current[index]??0);setTranscript(value=>({...value,segments:[...value.segments.slice(0,index),...parts,...value.segments.slice(index+1)]}));setTranscriptDirty(true)}catch(e){setError((e as Error).message)}}
  async function remove(){if(!window.confirm('¿Eliminar esta grabación, su archivo y la transcripción?'))return;setBusy(true);try{await api(path,{method:'DELETE'});onDirty(false);onDeleted()}catch(e){setError((e as Error).message);setBusy(false)}}
  function replaceClaim(updated:Claim){setClaimRun(value=>value?{...value,claims:(value.claims||[]).map(claim=>claim.id===updated.id?updated:claim)}:value)}
  async function extractClaims(){const count=transcript.segments.filter(segment=>!segment.reviewed).length;if(count&&!window.confirm(`Hay ${count} segmento${count===1?'':'s'} sin revisión manual. ¿Extraer de todas formas?`))return;setBusy(true);setError('');try{const run=await api<ClaimRun>(path+'/claim-extraction',{method:'POST'});setClaimRun(run)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function cancelClaims(){setBusy(true);setError('');try{setClaimRun(await api<ClaimRun>(path+'/claim-extraction/cancel',{method:'POST'}))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function editClaim(claim:Claim,normalizedText:string,category:ClaimCategory,segmentIds:string[]){setBusy(true);setError('');try{replaceClaim(await api<Claim>(`/claims/${claim.id}`,json('PUT',{revision:claim.revision,normalized_text:normalizedText,category,segment_ids:segmentIds})))}catch(e){setError((e as Error).message);throw e}finally{setBusy(false)}}
  async function selectClaim(claim:Claim,action:'accept'|'discard'){setBusy(true);setError('');try{replaceClaim(await api<Claim>(`/claims/${claim.id}/${action}`,json('POST',{revision:claim.revision})))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  if(!record)return <section className="panel"><p role={error?'alert':'status'}>{error||'Cargando grabación…'}</p></section>

  return <>
    <header className="workspace-header"><div><p className="eyebrow">{kinds[record.kind]} · {formatTime(record.duration_ms)}</p><h1>{record.title}</h1></div><span className="badge">{statuses[record.status]||record.status}</span></header>
    <div className="toolbar"><button disabled={busy||processing||dirty} onClick={()=>{if(transcript.segments.length&&!window.confirm('Volver a transcribir reemplazará la revisión cuando termine. ¿Continuar?'))return;void action('transcribe')}}>Transcribir</button>{processing&&<button disabled={busy} onClick={()=>void action('cancel')}>Cancelar trabajo</button>}<button className="danger" disabled={busy} onClick={()=>void remove()}>Eliminar</button></div>
    {(error||record.error)&&<p className="error" role="alert">{error||record.error}</p>}{notice&&<p role="status" className="notice">{notice}</p>}
    {dirty&&<div className="save-bar" role="status"><strong>Cambios sin guardar</strong><button className="primary" disabled={busy||processing} onClick={()=>void save()}>{busy?'Guardando…':'Guardar revisión'}</button></div>}
    <div className={`workspace-layout ${editor?'editor-open':''}`}>
      <section className="workspace-main">
        <video ref={player} controls preload="metadata" src={`/api${path}/media`} onTimeUpdate={e=>setTime(e.currentTarget.currentTime)} onError={()=>setError('No se pudo reproducir el archivo. Comprueba el formato y la conexión.')} className={record.filename.toLowerCase().endsWith('.mp4')?'':'audio-player'}/>
        <div className="player-caption"><span>{formatTime(time*1000)} / {formatTime(record.duration_ms)}</span><label className="inline">Velocidad<select aria-label="Velocidad de reproducción" defaultValue="1" onChange={e=>{if(player.current)player.current.playbackRate=Number(e.target.value)}}>{[0.75,1,1.25,1.5,2].map(n=><option key={n} value={n}>{n}×</option>)}</select></label></div>
        <ClaimsPanel run={claimRun} segments={transcript.segments} busy={busy||processing||dirty} onStart={()=>void extractClaims()} onCancel={()=>void cancelClaims()} onSeek={milliseconds=>{if(player.current){player.current.currentTime=milliseconds/1000;setTime(player.current.currentTime)}}} onEdit={editClaim} onSelect={selectClaim} onDraftDirty={setClaimDirty}/>
        <div className="editor-toggles">
          <button ref={speakerButton} aria-expanded={editor==='speakers'} aria-controls="secondary-editor" onClick={()=>setEditor(value=>value==='speakers'?null:'speakers')}><span>{editor==='speakers'?'▾':'▸'} Identificar hablantes · {speakers.length} detectado{speakers.length===1?'':'s'}</span><small>{speakers.map((speaker,index)=>speaker.name||`Hablante ${index+1}`).join(', ')||'Sin hablantes asignados'}{speakerDirty&&<strong>Cambios pendientes</strong>}</small></button>
          <button ref={transcriptButton} aria-expanded={editor==='transcript'} aria-controls="secondary-editor" onClick={()=>setEditor(value=>value==='transcript'?null:'transcript')}><span>{editor==='transcript'?'▾':'▸'} Editar transcripción · {transcript.segments.length} segmentos</span><small>{transcript.segments.filter(segment=>!segment.reviewed).length} sin revisión manual{transcriptDirty&&<strong>Cambios pendientes</strong>}</small></button>
        </div>
      </section>
      <aside id="secondary-editor" className="secondary-panel" hidden={!editor} aria-labelledby="secondary-title"><header><div><p className="eyebrow">EDITOR</p><h2 id="secondary-title">{editor==='speakers'?'Quién habla':'Transcripción'}</h2></div><button aria-label="Cerrar editor" onClick={closeEditor}>×</button></header>
      {editor==='speakers'?<div className="secondary-scroll"><p className="muted">{speakers.length} detectado{speakers.length===1?'':'s'}. Asigna nombres y roles a las voces.</p><fieldset disabled={busy||processing}>{speakers.map((speaker,i)=><div className="speaker-row" key={speaker.id}><label>Hablante {i+1}<input value={speaker.name} maxLength={100} placeholder={speaker.id} onChange={e=>{setSpeakers(values=>values.map((v,j)=>j===i?{...v,name:e.target.value}:v));setSpeakerDirty(true)}}/></label><label>Rol<select value={speaker.role} onChange={e=>{setSpeakers(values=>values.map((v,j)=>j===i?{...v,role:e.target.value as Speaker['role']}:v));setSpeakerDirty(true)}}>{Object.entries({unspecified:'Sin especificar',speaker:'Orador',moderator:'Moderador',interviewer:'Entrevistador',guest:'Invitado'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label></div>)}<button disabled={speakers.length>=4} onClick={()=>{setSpeakers([...speakers,{id:crypto.randomUUID(),name:'',role:'unspecified'}]);setSpeakerDirty(true)}}>Añadir hablante</button></fieldset></div>:
      <div className="transcript-panel"><div className="transcript-header"><span>{transcript.segments.length} segmentos</span><label className="inline"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>Seguir reproducción</label></div>
        <div className="transcript-scroll">{!transcript.segments.length&&<p className="empty">{processing?'Procesando la grabación. Puedes volver más tarde.':'Solicita la transcripción o añade segmentos manualmente para revisar el contenido.'}</p>}
          {transcript.segments.map((segment,index)=><article ref={node=>{rows.current[index]=node}} key={segment.id??`new-${index}`} className={`segment ${active.includes(index)?'active':''}`}>
            <div className="segment-heading"><button className="time-link" onClick={()=>{if(player.current){player.current.currentTime=Math.max(0,segment.start_ms/1000-2);setTime(player.current.currentTime)}}}>{formatTime(segment.start_ms)} ↗</button><span className="muted">{segment.reviewed?'Revisado':'Sin revisión manual'}</span></div>
            <fieldset disabled={busy||processing}>
              <label>Hablante<select value={segment.speaker_id??''} onChange={e=>changeSegment(index,{speaker_id:e.target.value||null})}><option value="">Sin determinar / voces superpuestas</option>{speakers.map((s,i)=><option key={s.id} value={s.id}>{s.name||`Hablante ${i+1}`}</option>)}</select></label>
              <label>Texto<textarea rows={3} value={segment.text} onSelect={e=>{cursors.current[index]=e.currentTarget.selectionStart}} onChange={e=>changeSegment(index,{text:e.target.value})}/></label>
              <div className="form-grid"><label>Inicio (segundos)<input type="number" min="0" step="0.001" value={segment.start_ms/1000} onChange={e=>changeSegment(index,{start_ms:Math.round(Number(e.target.value)*1000)})}/></label><label>Fin (segundos)<input type="number" min="0" step="0.001" value={segment.end_ms/1000} onChange={e=>changeSegment(index,{end_ms:Math.round(Number(e.target.value)*1000)})}/></label></div>
              <div className="segment-actions"><button title="Pausa el reproductor en el punto de corte y coloca el cursor en el texto" onClick={()=>split(index)}>Dividir aquí</button><button onClick={()=>{setTranscript(value=>({...value,segments:value.segments.filter((_,i)=>i!==index)}));setTranscriptDirty(true)}}>Quitar segmento</button></div>
            </fieldset>
          </article>)}
        </div><div className="transcript-footer"><button disabled={busy||processing} onClick={()=>{const start=Math.min(Math.round(time*1000),Math.max(0,record.duration_ms-1));setTranscript(value=>({...value,segments:[...value.segments,{start_ms:start,end_ms:Math.min(start+5000,record.duration_ms),text:'',speaker_id:null,reviewed:false}]}));setTranscriptDirty(true)}}>Añadir segmento en este momento</button></div>
      </div>}
      </aside>
    </div>
  </>
}
