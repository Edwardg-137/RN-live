export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch('/api' + path, init)
  if (!response.ok) {
    let message = `Error ${response.status}`
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : 'Revisa los datos introducidos.' } catch { /* Respuesta sin JSON. */ }
    throw new Error(message)
  }
  return response.status === 204 ? undefined as T : response.json()
}
export function json(method:string, body:unknown):RequestInit {
  return {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}
}
