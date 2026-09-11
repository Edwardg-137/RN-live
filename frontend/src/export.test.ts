import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildExport, canDownloadTranscript, downloadJson, exportFilename } from './export'
import type { ClaimRun, Recording, Speaker, Transcript } from './types'

const recording: Recording = {
  id: 'recording-1', title: 'Entrevista: Año 2026 / prueba', kind: 'interview', speaker_count: 2,
  filename: 'private/source.mp4', duration_ms: 3000, status: 'ready_for_review', error: null,
  revision: 3, content_date: '2026-09-10', scope: 'Guatemala', speakers: [],
}
const speakers: Speaker[] = [{id: 'a', name: 'Ana local', role: 'guest'}]
const transcript: Transcript = {revision: 4, segments: [
  {id: 's1', start_ms: 0, end_ms: 1000, text: 'Texto local sin guardar', speaker_id: 'a', reviewed: true},
  {id: 's2', start_ms: 1000, end_ms: 2000, text: 'Segundo segmento de prueba', speaker_id: null, reviewed: false},
]}
const analysis: ClaimRun = {
  id: 'run-1', recording_id: 'recording-1', recording_revision: 3, kind: 'claim_extraction', status: 'stale',
  provider: 'openrouter', model: 'free/model', prompt_version: 'claims-v2-conversation', usage: {total_tokens: 12},
  error: null, unreviewed_segment_count: 1, created_at: '2026-09-10T00:00:00', completed_at: '2026-09-10T00:00:01',
  claims: [{
    id: 'claim-1', status: 'proposed', revision: 0, normalized_text: 'Texto guardado.', original_quote: 'Texto local',
    category: 'fact', verifiable: true, start_ms: 0, end_ms: 1000, ambiguity_notes: [], missing_context: [],
    conversation_relation: 'answer', context_required: true, standalone_text: 'Texto guardado.',
    segments: [{segment_id: 's1', start_ms: 0, end_ms: 1000, speaker_id: 'a', speaker_name: 'Ana', position: 0, relation: 'source'}],
    context_segments: [{segment_id: 's2', start_ms: 1000, end_ms: 2000, speaker_id: null, speaker_name: null, position: 0, relation: 'context'}],
  }],
}

describe('exportación JSON', () => {
  afterEach(()=>vi.restoreAllMocks())
  it('bloquea la descarga hasta que haya una transcripción disponible', () => {
    expect(canDownloadTranscript('received', [])).toBe(false)
    expect(canDownloadTranscript('ready_for_review', [])).toBe(true)
    expect(canDownloadTranscript('failed', transcript.segments)).toBe(true)
  })

  it('construye únicamente el estado visible permitido y superpone el borrador local', () => {
    const result = buildExport({
      recording, speakers, transcript, analysis, containsUnsavedChanges: true,
      analysisIsStale: true,
      claimDraft: {claimId: 'claim-1', normalizedText: 'Texto editado localmente.', category: 'opinion', segmentIds: ['s2']},
      exportedAt: '2026-09-10T12:00:00.000Z',
    })

    expect(result.schema_version).toBe('rn-live-export-v1')
    expect(result.exported_at).toBe('2026-09-10T12:00:00.000Z')
    expect(result.recording).toEqual({id: 'recording-1', title: 'Entrevista: Año 2026 / prueba', kind: 'interview', duration_ms: 3000, content_date: '2026-09-10', scope: 'Guatemala', revision: 4})
    expect(result.speakers).toEqual(speakers)
    expect(result.segments).toEqual(transcript.segments)
    expect(result.analysis?.claims?.[0]).toMatchObject({normalized_text: 'Texto editado localmente.', standalone_text: 'Texto editado localmente.', category: 'opinion', start_ms: 1000, end_ms: 2000})
    expect(result.analysis?.recording_id).toBe('recording-1')
    expect(result.analysis?.claims?.[0].segments.map(link=>link.segment_id)).toEqual(['s2'])
    expect(result.analysis?.claims?.[0].context_segments).toEqual([])
    expect(result.export_state).toEqual({contains_unsaved_changes: true, analysis_is_stale: true})
    expect(result.metrics).toEqual({
      segments_total: 2, segments_reviewed: 1, short_segments: 0, segments_without_speaker: 1,
      duration_by_speaker: [{speaker_id: 'a', speaker_name: 'Ana local', duration_ms: 1000}],
      overlaps: 0, invalid_segments: 0,
      claims_by_category: {opinion: 1}, claims_by_status: {proposed: 1},
    })

    const serialized = JSON.stringify(result)
    for(const forbidden of ['filename','private/source.mp4','api_key','"token":','/api/recordings'])expect(serialized).not.toContain(forbidden)
  })

  it('exporta analysis null y genera un nombre seguro', () => {
    const result = buildExport({recording, speakers, transcript, analysis: null, containsUnsavedChanges: true, analysisIsStale: true, claimDraft: null, exportedAt: '2026-09-10T12:00:00.000Z'})
    expect(result.analysis).toBeNull()
    expect(result.export_state).toEqual({contains_unsaved_changes: true, analysis_is_stale: false})
    expect(exportFilename(recording.title, transcript.revision)).toBe('entrevista-ano-2026-prueba-revision-4.json')
  })

  it('marca el análisis como desactualizado por cambios locales aunque el servidor diga completed', () => {
    const result = buildExport({recording, speakers, transcript, analysis: {...analysis, status: 'completed'}, containsUnsavedChanges: true, analysisIsStale: true, claimDraft: null, exportedAt: '2026-09-10T12:00:00.000Z'})
    expect(result.export_state.analysis_is_stale).toBe(true)
  })

  it('no copia propiedades sensibles inesperadas de la API', () => {
    const unsafeRecording = {...recording, storage_path: 'private/source.mp4', api_key: 'secret-value'} as Recording
    const unsafeSpeakers = [{...speakers[0], token: 'secret-value'}] as unknown as Speaker[]
    const unsafeTranscript = {revision: transcript.revision, segments: transcript.segments.map(segment=>({...segment, headers: {authorization: 'Bearer secret-value'}}))} as Transcript
    const unsafeAnalysis = {...analysis, error: 'secret-value', raw_response: 'secret-value', usage: {total_tokens: 12, authorization: 'Bearer secret-value'}} as ClaimRun
    const result = buildExport({recording: unsafeRecording, speakers: unsafeSpeakers, transcript: unsafeTranscript, analysis: unsafeAnalysis, containsUnsavedChanges: false, analysisIsStale: true, claimDraft: null, exportedAt: '2026-09-10T12:00:00.000Z'})

    expect(JSON.stringify(result)).not.toContain('secret-value')
    expect(result.analysis?.usage).toEqual({total_tokens: 12})
  })

  it('descarga JSON legible con MIME correcto y revoca la URL temporal', async () => {
    const link={href:'',download:'',click:vi.fn(),remove:vi.fn()}
    vi.stubGlobal('document',{createElement:vi.fn(()=>link),body:{appendChild:vi.fn()}})
    const create=vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:export')
    const revoke=vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined)

    downloadJson({texto:'á'},'prueba.json')

    const blob=create.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/json')
    expect(await blob.text()).toBe('{\n  "texto": "á"\n}')
    expect(link).toMatchObject({href:'blob:export',download:'prueba.json'})
    expect(link.click).toHaveBeenCalledOnce()
    expect(link.remove).toHaveBeenCalledOnce()
    expect(revoke).toHaveBeenCalledWith('blob:export')
  })
})
