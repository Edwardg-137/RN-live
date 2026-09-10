import type { Claim, ClaimCategory } from './types'

export function filterClaims(claims:Claim[],status:string,category:string){
  return claims.filter(claim=>(status==='all'||claim.status===status)&&(category==='all'||claim.category===category))
}

export function claimSpeakers(claim:Claim){
  return [...new Set(claim.segments.map(link=>link.speaker_name).filter((name):name is string=>Boolean(name)))].join(', ')||'Sin determinar'
}

export function claimEditBody(claim:Claim,normalizedText:string,category:ClaimCategory,segmentIds:string[]){
  return {revision:claim.revision,normalized_text:normalizedText.trim(),category,segment_ids:segmentIds}
}
