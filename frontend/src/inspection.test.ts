import { describe, expect, it } from 'vitest'
import { filterSegments, nearbySegments, transcriptSummary } from './inspection'
import type { Claim, Segment, Speaker } from './types'

const speakers: Speaker[] = [
  {id: 'a', name: 'Ana', role: 'guest'},
  {id: 'b', name: 'Beto', role: 'interviewer'},
]
const segments: Segment[] = [
  {id: 's0', start_ms: 0, end_ms: 500, text: '¿Por qué?', speaker_id: 'b', reviewed: true},
  {id: 's1', start_ms: 400, end_ms: 1400, text: 'Porque aumentó el presupuesto anual.', speaker_id: 'a', reviewed: true},
  {id: 's2', start_ms: 1500, end_ms: 1400, text: '   ', speaker_id: null, reviewed: false},
  {id: 's3', start_ms: 1600, end_ms: 2200, text: 'Eso es todo.', speaker_id: 'a', reviewed: false},
]
const claims: Claim[] = [
  {id:'c1',status:'proposed',revision:0,normalized_text:'Dato',original_quote:'Dato',category:'fact',verifiable:true,start_ms:400,end_ms:1400,ambiguity_notes:['Duda'],missing_context:[],conversation_relation:'answer',context_required:true,standalone_text:'Dato',segments:[{segment_id:'s1',start_ms:400,end_ms:1400,speaker_id:'a',speaker_name:'Ana',position:0}],context_segments:[]},
  {id:'c2',status:'accepted',revision:1,normalized_text:'Otro',original_quote:'Otro',category:'opinion',verifiable:false,start_ms:0,end_ms:2200,ambiguity_notes:[],missing_context:[],conversation_relation:'standalone',context_required:false,standalone_text:'Otro',segments:[{segment_id:'s0',start_ms:0,end_ms:500,speaker_id:'b',speaker_name:'Beto',position:0},{segment_id:'s3',start_ms:1600,end_ms:2200,speaker_id:'a',speaker_name:'Ana',position:1}],context_segments:[]},
]

describe('inspección descriptiva', () => {
  it('resume transcript y candidatas sin asignar una puntuación', () => {
    expect(transcriptSummary(segments, speakers, claims)).toEqual({
      segments_total: 4, segments_reviewed: 2, short_segments: 3, segments_without_speaker: 1,
      duration_by_speaker: [
        {speaker_id: 'a', speaker_name: 'Ana', duration_ms: 1600},
        {speaker_id: 'b', speaker_name: 'Beto', duration_ms: 500},
      ],
      overlaps: 1, invalid_segments: 1,
      claims_by_category: {fact: 1, opinion: 1}, claims_by_status: {proposed: 1, accepted: 1},
    })
  })

  it('filtra segmentos conservando sus índices originales', () => {
    expect(filterSegments(segments, 'short').map(item=>item.index)).toEqual([0,2,3])
    expect(filterSegments(segments, 'unreviewed').map(item=>item.index)).toEqual([2,3])
    expect(filterSegments(segments, 'no_speaker').map(item=>item.index)).toEqual([2])
  })

  it('separa fuentes de dos turnos anteriores y uno posterior', () => {
    expect(nearbySegments(claims[0], segments)).toEqual({
      source: [{segment: segments[1], index: 1}],
      nearby: [{segment: segments[0], index: 0}, {segment: segments[2], index: 2}],
    })
  })

  it('expande turnos completos y no un número fijo de segmentos', () => {
    const dialogue:Segment[]=[
      {id:'p1',start_ms:0,end_ms:100,text:'Primer turno',speaker_id:'a',reviewed:true},
      {id:'p2',start_ms:100,end_ms:200,text:'Pregunta parte uno',speaker_id:'b',reviewed:true},
      {id:'p3',start_ms:200,end_ms:300,text:'Pregunta parte dos',speaker_id:'b',reviewed:true},
      {id:'source',start_ms:300,end_ms:400,text:'Respuesta principal',speaker_id:'a',reviewed:true},
      {id:'n1',start_ms:400,end_ms:500,text:'Réplica parte uno',speaker_id:'b',reviewed:true},
      {id:'n2',start_ms:500,end_ms:600,text:'Réplica parte dos',speaker_id:'b',reviewed:true},
      {id:'later',start_ms:600,end_ms:700,text:'Turno posterior',speaker_id:'a',reviewed:true},
    ]
    const claim={...claims[0],segments:[{...claims[0].segments[0],segment_id:'source'}]}
    expect(nearbySegments(claim,dialogue).nearby.map(item=>item.segment.id)).toEqual(['p1','p2','p3','n1','n2'])
  })
})
