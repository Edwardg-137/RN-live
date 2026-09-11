import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ClaimsPanel } from './ClaimsPanel'
import type { ClaimRun } from './types'

const run: ClaimRun = {
  id: 'run-1', recording_id: 'recording-1', recording_revision: 4, kind: 'claim_extraction', status: 'completed',
  provider: 'openrouter', model: 'free/model', prompt_version: 'claims-v1', usage: {total_tokens: 42}, error: null,
  unreviewed_segment_count: 1, created_at: '2026-09-09T00:00:00', completed_at: '2026-09-09T00:00:02',
  claims: [{
    id: 'claim-1', status: 'proposed', revision: 0, normalized_text: 'Júpiter es grande.', original_quote: '«Júpiter es muy grande»',
    category: 'fact', verifiable: true, start_ms: 61000, end_ms: 63000,
    ambiguity_notes: ['“grande” requiere una comparación'], missing_context: ['Magnitud concreta'],
    segments: [{segment_id: 's1', start_ms: 61000, end_ms: 63000, speaker_id: 'a', speaker_name: 'Ana', position: 0}],
  }, {
    id: 'claim-2', status: 'proposed', revision: 0, normalized_text: 'Saturno tiene anillos.', original_quote: 'Saturno tiene anillos',
    category: 'fact', verifiable: true, start_ms: 64000, end_ms: 66000,
    ambiguity_notes: [], missing_context: [],
    segments: [{segment_id: 's1', start_ms: 64000, end_ms: 66000, speaker_id: 'a', speaker_name: 'Ana', position: 0}],
  }],
}

const props = {
  run,
  segments: [{id: 's1', start_ms: 61000, end_ms: 63000, text: 'Júpiter es muy grande', speaker_id: 'a', reviewed: true}],
  busy: false,
  onStart: () => undefined,
  onCancel: () => undefined,
  onSeek: () => undefined,
  onEdit: () => undefined,
  onSelect: () => undefined,
}

describe('panel de afirmaciones', () => {
  it('muestra todos los datos de revisión y mantiene la cita como lectura', () => {
    const html = renderToStaticMarkup(createElement(ClaimsPanel, props))
    expect(html).toContain('«Júpiter es muy grande»')
    expect(html).toContain('Ana')
    expect(html).toContain('01:01')
    expect(html).toContain('Hecho')
    expect(html).toContain('Verificable')
    expect(html).toContain('“grande” requiere una comparación')
    expect(html).toContain('Magnitud concreta')
    expect(html).toContain('Aceptar')
    expect(html).toContain('Descartar')
    expect(html).not.toContain('name="original_quote"')
  })

  it('mantiene visibles las candidatas cuando la ejecución está desactualizada', () => {
    const html = renderToStaticMarkup(createElement(ClaimsPanel, {...props, run: {...run, status: 'stale'}}))
    expect(html).toContain('desactualizada')
    expect(html).toContain('Júpiter es grande.')
  })

  it('expone una lista horizontal con una sola tarjeta activa y navegación accesible', () => {
    const html = renderToStaticMarkup(createElement(ClaimsPanel, props))
    expect(html).toContain('aria-label="Carrusel de afirmaciones"')
    expect(html).toContain('aria-label="Afirmación anterior"')
    expect(html).toContain('aria-label="Afirmación siguiente"')
    expect(html).toContain('1 de 2')
    expect(html).toContain('aria-current="true"')
    expect(html).toMatch(/Saturno tiene anillos[\s\S]*tabindex="-1"/)
  })
})
