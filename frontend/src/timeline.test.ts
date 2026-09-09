import { describe, expect, it } from 'vitest'
import { activeSegments, formatTime, splitSegment } from './timeline'

describe('línea temporal', () => {
  it('usa intervalos semiabiertos y conserva superposiciones', () => {
    const parts = [{start_ms: 0, end_ms: 1000}, {start_ms: 500, end_ms: 1500}]
    expect(activeSegments(parts, 0.75)).toEqual([0, 1])
    expect(activeSegments(parts, 1)).toEqual([1])
    expect(activeSegments(parts, 1.5)).toEqual([])
  })
  it('formatea horas sin reiniciar los minutos', () => {
    expect(formatTime(3661000)).toBe('01:01:01')
    expect(formatTime(125000)).toBe('02:05')
  })
  it('divide un intervalo sin inventar texto para la segunda voz', () => {
    const segment = {id:'old', start_ms:0, end_ms:2000, text:'hola mundo', speaker_id:null, reviewed:false}
    const [first, second] = splitSegment(segment, 1000, 5)
    expect(first.text).toBe('hola')
    expect(second.text).toBe('mundo')
    expect(first.end_ms).toBe(second.start_ms)
    expect(second.id).toBeUndefined()
    expect(() => splitSegment(segment, 3000, 5)).toThrow()
  })
})
