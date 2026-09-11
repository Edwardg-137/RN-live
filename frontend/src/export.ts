import type { Claim, ClaimDraftState, ClaimLink, ClaimRun, Recording, Segment, Speaker, Transcript } from './types'
import { transcriptSummary } from './inspection'

type ExportInput = {
  recording: Recording
  speakers: Speaker[]
  transcript: Transcript
  analysis: ClaimRun|null
  containsUnsavedChanges: boolean
  analysisIsStale: boolean
  claimDraft: ClaimDraftState|null
  exportedAt: string
}

export function canDownloadTranscript(status:string,segments:Segment[]){return status==='ready_for_review'||segments.length>0}

function exportLink(link:ClaimLink){
  return {segment_id:link.segment_id,start_ms:link.start_ms,end_ms:link.end_ms,speaker_id:link.speaker_id,speaker_name:link.speaker_name,position:link.position,relation:link.relation}
}

function exportClaim(claim:Claim){
  return {
    id:claim.id,status:claim.status,revision:claim.revision,normalized_text:claim.normalized_text,
    standalone_text:claim.standalone_text,original_quote:claim.original_quote,category:claim.category,
    verifiable:claim.verifiable,start_ms:claim.start_ms,end_ms:claim.end_ms,
    ambiguity_notes:[...claim.ambiguity_notes],missing_context:[...claim.missing_context],
    conversation_relation:claim.conversation_relation,context_required:claim.context_required,
    segments:claim.segments.map(exportLink),context_segments:claim.context_segments.map(exportLink),
  }
}

function exportAnalysis(run:ClaimRun, transcript:Transcript, speakers:Speaker[], draft:ClaimDraftState|null){
  const speakerNames=new Map(speakers.map(speaker=>[speaker.id,speaker.name||null]))
  const claims=(run.claims||[]).map(claim=>{
    const value=exportClaim(claim)
    if(!draft||draft.claimId!==claim.id)return value
    const ids=new Set(draft.segmentIds)
    const links=transcript.segments.flatMap(segment=>segment.id&&ids.has(segment.id)?[{
      segment_id:segment.id,start_ms:segment.start_ms,end_ms:segment.end_ms,speaker_id:segment.speaker_id,
      speaker_name:segment.speaker_id?speakerNames.get(segment.speaker_id)??null:null,position:0,relation:'source' as const,
    }]:[]).map((link,position)=>({...link,position}))
    const context=value.context_segments.filter(link=>!ids.has(link.segment_id))
    return {...value,normalized_text:draft.normalizedText,standalone_text:draft.normalizedText,category:draft.category,
      start_ms:links.length?Math.min(...links.map(link=>link.start_ms)):value.start_ms,
      end_ms:links.length?Math.max(...links.map(link=>link.end_ms)):value.end_ms,
      segments:links,context_segments:context,context_required:value.context_required&&context.length>0}
  })
  const usage=Object.fromEntries(Object.entries(run.usage||{}).filter(([key,value])=>['prompt_tokens','completion_tokens','total_tokens','cost'].includes(key)&&typeof value==='number'))
  return {
    id:run.id,recording_id:run.recording_id,recording_revision:run.recording_revision,kind:run.kind,status:run.status,provider:run.provider,
    model:run.model,prompt_version:run.prompt_version,usage:Object.keys(usage).length?usage:null,
    unreviewed_segment_count:run.unreviewed_segment_count,created_at:run.created_at,completed_at:run.completed_at,claims,
  }
}

export function buildExport({recording,speakers,transcript,analysis,containsUnsavedChanges,analysisIsStale,claimDraft,exportedAt}:ExportInput){
  const exportedAnalysis=analysis?exportAnalysis(analysis,transcript,speakers,claimDraft):null
  return {
    schema_version:'rn-live-export-v1' as const,
    exported_at:exportedAt,
    recording:{
      id:recording.id,title:recording.title,kind:recording.kind,duration_ms:recording.duration_ms,
      content_date:recording.content_date,scope:recording.scope,revision:transcript.revision,
    },
    speakers:speakers.map(({id,name,role})=>({id,name,role})),
    segments:transcript.segments.map(({id,start_ms,end_ms,text,speaker_id,reviewed,original_text})=>({id,start_ms,end_ms,text,speaker_id,reviewed,original_text})),
    analysis:exportedAnalysis,
    metrics:transcriptSummary(transcript.segments,speakers,exportedAnalysis?.claims||[]),
    export_state:{contains_unsaved_changes:containsUnsavedChanges,analysis_is_stale:Boolean(analysis&&analysisIsStale)},
  }
}

export function exportFilename(title:string,revision:number){
  const safe=title.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'grabacion'
  return `${safe}-revision-${revision}.json`
}

export function downloadJson(value:unknown,filename:string){
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}))
  const link=document.createElement('a')
  link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url)
}
