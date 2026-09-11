import type { Claim, Segment, Speaker } from './types'

export type SegmentAudit = 'all'|'short'|'unreviewed'|'no_speaker'

function wordCount(text:string){return text.match(/[\p{L}\p{N}_]+/gu)?.length||0}

export function filterSegments(segments:Segment[],filter:SegmentAudit){
  return segments.map((segment,index)=>({segment,index})).filter(({segment})=>
    filter==='all'||
    (filter==='short'&&wordCount(segment.text)<=3)||
    (filter==='unreviewed'&&!segment.reviewed)||
    (filter==='no_speaker'&&!segment.speaker_id))
}

export function nearbySegments(claim:Claim,segments:Segment[]){
  const ids=new Set(claim.segments.map(link=>link.segment_id))
  const indexed=segments.map((segment,index)=>({segment,index}))
  const source=indexed.filter(({segment})=>Boolean(segment.id&&ids.has(segment.id)))
  if(!source.length)return {source:[],nearby:[]}
  const turns:number[]=[]
  let turn=0,previous:Segment['speaker_id']|undefined
  for(const segment of segments){if(segment.speaker_id!==previous){turn++;previous=segment.speaker_id}turns.push(turn)}
  const sourceTurns=source.map(item=>turns[item.index])
  const first=Math.min(...sourceTurns)-2,last=Math.max(...sourceTurns)+1
  const nearby=indexed.filter(({segment,index})=>turns[index]>=first&&turns[index]<=last&&(!segment.id||!ids.has(segment.id)))
  return {source,nearby}
}

export function transcriptSummary(segments:Segment[],speakers:Speaker[],claims:Claim[]){
  const durationById=new Map<string,number>()
  for(const segment of segments){
    if(segment.speaker_id&&segment.end_ms>segment.start_ms)durationById.set(segment.speaker_id,(durationById.get(segment.speaker_id)||0)+segment.end_ms-segment.start_ms)
  }
  const ordered=[...segments].filter(segment=>segment.end_ms>segment.start_ms).sort((a,b)=>a.start_ms-b.start_ms)
  let overlaps=0,maxEnd=-1
  for(const segment of ordered){if(segment.start_ms<maxEnd)overlaps++;maxEnd=Math.max(maxEnd,segment.end_ms)}
  const count=(key:'category'|'status')=>claims.reduce<Record<string,number>>((values,claim)=>{const value=claim[key];values[value]=(values[value]||0)+1;return values},{})
  return {
    segments_total:segments.length,
    segments_reviewed:segments.filter(segment=>segment.reviewed).length,
    short_segments:segments.filter(segment=>wordCount(segment.text)<=3).length,
    segments_without_speaker:segments.filter(segment=>!segment.speaker_id).length,
    duration_by_speaker:speakers.filter(speaker=>durationById.has(speaker.id)).map(speaker=>({speaker_id:speaker.id,speaker_name:speaker.name||speaker.id,duration_ms:durationById.get(speaker.id)||0})),
    overlaps,
    invalid_segments:segments.filter(segment=>!segment.text.trim()||segment.start_ms<0||segment.end_ms<=segment.start_ms).length,
    claims_by_category:count('category'),
    claims_by_status:count('status'),
  }
}
