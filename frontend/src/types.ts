export type Kind = 'speech' | 'debate' | 'interview'
export type Speaker = {id: string; name: string; role: 'unspecified' | 'speaker' | 'moderator' | 'interviewer' | 'guest'}
export type Segment = {id?: string; start_ms: number; end_ms: number; text: string; speaker_id: string | null; reviewed: boolean; original_text?: string}
export type Recording = {id: string; title: string; kind: Kind; speaker_count: number; filename: string; duration_ms: number; status: string; error: string | null; revision: number; speakers: Speaker[]; content_date: string | null; scope: string}
export type Transcript = {revision: number; segments: Segment[]}
export type Snapshot = Recording & {segments: Segment[]}
export const kinds: Record<Kind, string> = {speech: 'Discurso', debate: 'Debate', interview: 'Entrevista'}
export const statuses: Record<string, string> = {received:'Recibida', queued:'En cola', transcribing:'Transcribiendo', ready_for_review:'Lista para revisión', cancelled:'Cancelada', failed:'Error de procesamiento'}
