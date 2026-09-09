import type { Segment } from './types'

export function activeSegments(segments: {start_ms:number; end_ms:number}[], seconds:number):number[] {
  return segments.flatMap((segment, index) => segment.start_ms <= seconds * 1000 && seconds * 1000 < segment.end_ms ? [index] : [])
}

export function formatTime(milliseconds:number):string {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000)
  const parts = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
  return (parts[0] ? parts : parts.slice(1)).map(p => String(p).padStart(2,'0')).join(':')
}

export function splitSegment(segment:Segment, time:number, character:number):[Segment, Segment] {
  const firstText = segment.text.slice(0, character).trim()
  const secondText = segment.text.slice(character).trim()
  if (time <= segment.start_ms || time >= segment.end_ms || !firstText || !secondText) throw new Error('Coloca el video dentro del segmento y el cursor entre las palabras que quieras separar.')
  return [{...segment, text:firstText, end_ms:time}, {...segment, id:undefined, original_text:undefined, text:secondText, start_ms:time}]
}
