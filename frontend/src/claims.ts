import type { Claim, ClaimCategory } from './types'

export function filterClaims(claims:Claim[],status:string,category:string,audit='all'){
  return claims.filter(claim=>(status==='all'||claim.status===status)&&(category==='all'||claim.category===category)&&(
    audit==='all'||
    (audit==='issues'&&(claim.ambiguity_notes.length>0||claim.missing_context.length>0))||
    (audit==='multi_segment'&&claim.segments.length>1)
  ))
}

export function claimIndexAfterChange(previousIndex:number,count:number){
  return Math.max(0,Math.min(previousIndex,count-1))
}

export function claimSpeakers(claim:Claim){
  return [...new Set(claim.segments.map(link=>link.speaker_name).filter((name):name is string=>Boolean(name)))].join(', ')||'Sin determinar'
}

export function claimEditBody(claim:Claim,normalizedText:string,category:ClaimCategory,segmentIds:string[]){
  return {revision:claim.revision,normalized_text:normalizedText.trim(),category,segment_ids:segmentIds}
}
