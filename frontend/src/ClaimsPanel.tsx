import { useEffect, useMemo, useRef, useState } from 'react'
import { claimEditBody, claimIndexAfterChange, claimSpeakers, filterClaims } from './claims'
import { nearbySegments } from './inspection'
import { formatTime } from './timeline'
import type { Claim, ClaimCategory, ClaimDraftState, ClaimRun, Segment } from './types'
import './claims.css'

export const categoryLabels:Record<ClaimCategory,string> = {fact:'Hecho',opinion:'Opinión',prediction:'Predicción',question_premise:'Premisa de pregunta',unverifiable:'No verificable'}
const statusLabels:Record<Claim['status'],string> = {proposed:'Propuesta',accepted:'Aceptada',discarded:'Descartada',edited:'Editada',stale:'Desactualizada'}
const relationLabels:Record<Claim['conversation_relation'],string> = {standalone:'Independiente',answer:'Respuesta',reply:'Réplica',rebuttal:'Refutación',reported_speech:'Discurso referido'}

type Props = {
  run: ClaimRun|null
  segments: Segment[]
  busy: boolean
  onStart: () => void
  onCancel: () => void
  onSeek: (milliseconds:number) => void
  onEdit: (claim:Claim, normalizedText:string, category:ClaimCategory, segmentIds:string[]) => void|Promise<void>
  onSelect: (claim:Claim, action:'accept'|'discard') => void|Promise<void>
  locallyStale?: boolean
  onDraftDirty?: (dirty:boolean) => void
  onDraftChange?: (draft:ClaimDraftState|null) => void
}

type Draft = {normalizedText:string;category:ClaimCategory;segmentIds:string[]}

export function ClaimsPanel({run,segments,busy,onStart,onCancel,onSeek,onEdit,onSelect,locallyStale=false,onDraftDirty=()=>undefined,onDraftChange=()=>undefined}:Props){
  const [status,setStatus] = useState('all')
  const [category,setCategory] = useState('all')
  const [audit,setAudit] = useState('all')
  const [editing,setEditing] = useState<string|null>(null)
  const [draft,setDraft] = useState<Draft|null>(null)
  const [draftDirty,setDraftDirty] = useState(false)
  const [activeIndex,setActiveIndex] = useState(0)
  const track = useRef<HTMLDivElement>(null)
  const cards = useRef<(HTMLElement|null)[]>([])
  const claims = useMemo(()=>filterClaims(run?.claims||[],status,category,audit),[run?.claims,status,category,audit])
  const active = run?.status==='queued'||run?.status==='running'
  const persistedStale = run?.status==='stale'
  const stale = persistedStale||locallyStale
  const unreviewed = run?.unreviewed_segment_count ?? 0

  useEffect(()=>()=>{onDraftDirty(false);onDraftChange(null)},[onDraftDirty,onDraftChange])
  useEffect(()=>{setEditing(null);setDraft(null);setDraftDirty(false);onDraftDirty(false);onDraftChange(null)},[run?.id,run?.status,onDraftDirty,onDraftChange])
  useEffect(()=>setActiveIndex(index=>claimIndexAfterChange(index,claims.length)),[claims.length])

  function beginEdit(claim:Claim){
    setEditing(claim.id)
    setDraft({normalizedText:claim.normalized_text,category:claim.category,segmentIds:claim.segments.map(link=>link.segment_id)})
    onDraftDirty(false)
    onDraftChange(null)
  }
  function changeDraft(value:Draft){setDraft(value);setDraftDirty(true);onDraftDirty(true);if(editing)onDraftChange({claimId:editing,...value})}
  function stopEdit(){setEditing(null);setDraft(null);setDraftDirty(false);onDraftDirty(false);onDraftChange(null)}
  async function saveEdit(claim:Claim){
    if(!draft)return
    const body=claimEditBody(claim,draft.normalizedText,draft.category,draft.segmentIds)
    try{await onEdit(claim,body.normalized_text,body.category,body.segment_ids);stopEdit()}catch{/* El contenedor muestra el error y conserva el borrador. */}
  }
  function showClaim(index:number){const next=claimIndexAfterChange(index,claims.length);setActiveIndex(next);const card=cards.current[next];if(card&&track.current)track.current.scrollTo({left:Math.max(0,card.offsetLeft-track.current.offsetLeft-(track.current.clientWidth-card.offsetWidth)/2)})}

  return <section className="panel claims-panel" aria-labelledby="claims-title">
    <div className="panel-heading"><div><p className="eyebrow">ANÁLISIS ASISTIDO</p><h2 id="claims-title">Afirmaciones</h2></div>{active?<button disabled={busy} onClick={onCancel}>Cancelar extracción</button>:<button className="primary" disabled={busy||draftDirty||!segments.length} onClick={onStart}>{run?'Reanalizar':'Extraer afirmaciones'}</button>}</div>
    {!run&&<p className="muted">Extrae afirmaciones del transcript revisado y salta al momento exacto donde se dijeron.</p>}
    {unreviewed>0&&<p className="warning">La extracción se inició con {unreviewed} segmento{unreviewed===1?'':'s'} sin revisión manual.</p>}
    {run?.status==='queued'&&<p role="status" className="muted">Análisis en cola…</p>}
    {run?.status==='running'&&<p role="status" className="muted">Analizando con OpenRouter…</p>}
    {run?.status==='failed'&&<p role="alert" className="error">{run.error||'No se pudo completar el análisis.'}</p>}
    {run?.status==='cancelled'&&<p role="status" className="muted">Extracción cancelada. Puedes iniciar otra cuando quieras.</p>}
    {persistedStale&&<p role="status" className="warning">Esta extracción está desactualizada porque cambió la revisión de la transcripción. Las candidatas se conservan para consulta.</p>}
    {locallyStale&&!persistedStale&&<p role="status" className="warning">Este análisis no incluye los cambios locales de hablantes o transcripción. Guarda y vuelve a analizar para actualizarlo.</p>}
    {run&&(run.status==='completed'||stale)&&<>
      <div className="analysis-meta"><span>Revisión {run.recording_revision}</span><span>{run.model||'Modelo no informado'}</span>{typeof run.usage?.total_tokens==='number'&&<span>{run.usage.total_tokens} tokens</span>}</div>
      <div className="claim-filters"><label>Estado<select value={status} onChange={event=>{setStatus(event.target.value);setActiveIndex(0);track.current?.scrollTo({left:0})}}><option value="all">Todos</option>{Object.entries(statusLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Categoría<select value={category} onChange={event=>{setCategory(event.target.value);setActiveIndex(0);track.current?.scrollTo({left:0})}}><option value="all">Todas</option>{Object.entries(categoryLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Auditoría<select value={audit} onChange={event=>{setAudit(event.target.value);setActiveIndex(0);track.current?.scrollTo({left:0})}}><option value="all">Todas</option><option value="issues">Con ambigüedad o contexto faltante</option><option value="multi_segment">Con varias fuentes</option></select></label></div>
      {!claims.length?<p className="muted claims-empty">No hay candidatas para los filtros seleccionados.</p>:<>
      <div className="claim-navigation"><button aria-label="Afirmación anterior" disabled={activeIndex===0} onClick={()=>showClaim(activeIndex-1)}>←</button><span aria-live="polite">{activeIndex+1} de {claims.length}</span><button aria-label="Afirmación siguiente" disabled={activeIndex===claims.length-1} onClick={()=>showClaim(activeIndex+1)}>→</button></div>
      <div ref={track} className="claims-list" role="list" aria-label="Carrusel de afirmaciones" tabIndex={0} onKeyDown={event=>{if(event.target!==event.currentTarget)return;if(event.key==='ArrowLeft'){event.preventDefault();showClaim(activeIndex-1)}if(event.key==='ArrowRight'){event.preventDefault();showClaim(activeIndex+1)}}} onScrollEnd={event=>{const center=event.currentTarget.scrollLeft+event.currentTarget.clientWidth/2;let nearest=0;let distance=Infinity;cards.current.forEach((card,index)=>{if(!card)return;const next=Math.abs(card.offsetLeft-event.currentTarget.offsetLeft+card.offsetWidth/2-center);if(next<distance){nearest=index;distance=next}});setActiveIndex(nearest)}}>{claims.map((claim,index)=>{const current=index===activeIndex;const inspection=nearbySegments(claim,segments);return <article ref={node=>{cards.current[index]=node}} role="listitem" aria-current={current?'true':undefined} className={`claim-card claim-${claim.status} ${current?'active':''}`} key={claim.id}>
        <div className="claim-heading"><button tabIndex={current?0:-1} className="time-link" onClick={()=>onSeek(claim.start_ms)}>{formatTime(claim.start_ms)}–{formatTime(claim.end_ms)} ↗</button><span className="badge">{statusLabels[claim.status]}</span></div>
        <p className="claim-speaker">{claimSpeakers(claim)}</p>
        <blockquote>{claim.original_quote}</blockquote>
        {editing===claim.id&&draft?<form onSubmit={event=>{event.preventDefault();void saveEdit(claim)}}>
          <label>Texto normalizado<textarea name="normalized_text" rows={3} maxLength={2000} value={draft.normalizedText} onChange={event=>changeDraft({...draft,normalizedText:event.target.value})}/></label>
          <label>Categoría<select value={draft.category} onChange={event=>changeDraft({...draft,category:event.target.value as ClaimCategory})}>{Object.entries(categoryLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
          <fieldset><legend>Segmentos vinculados</legend>{segments.map(segment=><label className="claim-segment-option" key={segment.id}><input type="checkbox" checked={Boolean(segment.id&&draft.segmentIds.includes(segment.id))} onChange={event=>{if(!segment.id)return;changeDraft({...draft,segmentIds:event.target.checked?[...draft.segmentIds,segment.id]:draft.segmentIds.filter(id=>id!==segment.id)})}}/>{formatTime(segment.start_ms)} · {segment.text}</label>)}</fieldset>
          <div className="claim-actions"><button className="primary" type="submit" disabled={busy||!draft.normalizedText.trim()||!draft.segmentIds.length}>Guardar candidata</button><button type="button" onClick={stopEdit}>Cancelar edición</button></div>
        </form>:<><p className="normalized-claim">{claim.standalone_text}</p><div className="claim-details"><span>{categoryLabels[claim.category]}</span><span>{claim.verifiable?'Verificable':'No verificable'}</span><span>{relationLabels[claim.conversation_relation]}</span></div>
          {inspection.source.length>0&&<details className="claim-context"><summary>Segmentos fuente</summary><ul>{inspection.source.map(({segment})=><li key={segment.id}><button tabIndex={current?0:-1} type="button" onClick={()=>onSeek(segment.start_ms)}>{formatTime(segment.start_ms)} · {segment.text}</button></li>)}</ul></details>}
          {claim.context_segments.length>0&&<details className="claim-context"><summary>Contexto usado{claim.context_required?' · necesario':''}</summary><ul>{claim.context_segments.map(link=><li key={link.segment_id}><button tabIndex={current?0:-1} type="button" onClick={()=>onSeek(link.start_ms)}>{formatTime(link.start_ms)} · {link.speaker_name||'Hablante sin determinar'}</button></li>)}</ul></details>}
          {inspection.nearby.length>0&&<details className="claim-context"><summary>Contexto cercano · no implica uso por el modelo</summary><ul>{inspection.nearby.map(({segment,index:segmentIndex})=><li key={segment.id??segmentIndex}><button tabIndex={current?0:-1} type="button" onClick={()=>onSeek(segment.start_ms)}>{formatTime(segment.start_ms)} · {segment.text}</button></li>)}</ul></details>}
          {claim.ambiguity_notes.length>0&&<div><strong>Ambigüedades</strong><ul>{claim.ambiguity_notes.map(note=><li key={note}>{note}</li>)}</ul></div>}
          {claim.missing_context.length>0&&<div><strong>Información faltante</strong><ul>{claim.missing_context.map(note=><li key={note}>{note}</li>)}</ul></div>}
          <div className="claim-actions"><button tabIndex={current?0:-1} disabled={busy||stale} onClick={()=>beginEdit(claim)}>Editar</button><button tabIndex={current?0:-1} disabled={busy||stale||claim.status==='accepted'} onClick={()=>void onSelect(claim,'accept')}>Aceptar</button><button tabIndex={current?0:-1} disabled={busy||stale||claim.status==='discarded'} onClick={()=>void onSelect(claim,'discard')}>Descartar</button></div></>}
      </article>})}</div></>}
    </>}
  </section>
}
