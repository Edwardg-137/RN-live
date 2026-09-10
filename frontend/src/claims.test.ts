import { describe, expect, it } from 'vitest'
import * as claimModule from './claims'
import type { Claim } from './types'

const claimTools = claimModule as typeof claimModule & {
  filterClaims: (claims: Claim[], status: string, category: string) => Claim[]
  claimSpeakers: (claim: Claim) => string
  claimEditBody: (claim: Claim, normalizedText: string, category: Claim['category'], segmentIds: string[]) => unknown
}

const claims: Claim[] = [
  {
    id: 'c1', status: 'proposed', revision: 0, normalized_text: 'Júpiter es grande.', original_quote: 'Júpiter es grande',
    category: 'fact', verifiable: true, start_ms: 0, end_ms: 700, ambiguity_notes: [], missing_context: [],
    segments: [{segment_id: 's1', start_ms: 0, end_ms: 700, speaker_id: 'a', speaker_name: 'Ana', position: 0}],
  },
  {
    id: 'c2', status: 'discarded', revision: 3, normalized_text: 'Quizá lleguemos.', original_quote: 'Quizá lleguemos',
    category: 'prediction', verifiable: false, start_ms: 800, end_ms: 1500, ambiguity_notes: ['Fecha imprecisa'], missing_context: ['Destino'],
    segments: [{segment_id: 's2', start_ms: 800, end_ms: 1500, speaker_id: null, speaker_name: null, position: 0}],
  },
]

describe('revisión de afirmaciones', () => {
  it('filtra conjuntamente por estado y categoría', () => {
    expect(claimTools.filterClaims(claims, 'discarded', 'prediction').map(claim => claim.id)).toEqual(['c2'])
    expect(claimTools.filterClaims(claims, 'all', 'fact').map(claim => claim.id)).toEqual(['c1'])
    expect(claimTools.filterClaims(claims, 'proposed', 'all').map(claim => claim.id)).toEqual(['c1'])
  })

  it('presenta los hablantes conservados sin duplicados', () => {
    const repeated = {...claims[0], segments: [...claims[0].segments, {...claims[0].segments[0], segment_id: 's3'}]}
    expect(claimTools.claimSpeakers(repeated)).toBe('Ana')
    expect(claimTools.claimSpeakers(claims[1])).toBe('Sin determinar')
  })

  it('construye una edición versionada sin incluir la cita original', () => {
    expect(claimTools.claimEditBody(claims[0], '  Júpiter tiene lunas.  ', 'fact', ['s2'])).toEqual({
      revision: 0,
      normalized_text: 'Júpiter tiene lunas.',
      category: 'fact',
      segment_ids: ['s2'],
    })
  })
})
