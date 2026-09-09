import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { Upload } from './Upload'
import { Workspace } from './Workspace'
import { formatTime } from './timeline'
import { kinds, statuses, type Recording } from './types'

export default function App(){
  const [items,setItems]=useState<Recording[]>([])
  const [selected,setSelected]=useState<string|null>(null)
  const [dirty,setDirty]=useState(false)
  const [error,setError]=useState('')
  const refresh=useCallback(()=>{api<Recording[]>('/recordings').then(setItems).catch(e=>setError(e.message))},[])
  useEffect(refresh,[refresh])
  function navigate(id:string|null){if(id===selected)return;if(dirty&&!window.confirm('Tienes cambios sin guardar. ¿Descartarlos?'))return;setDirty(false);setSelected(id)}
  return <div className="app"><aside className="sidebar"><div className="brand">RN-live<span>Grabaciones</span></div><button className="primary new-recording" onClick={()=>navigate(null)}>＋ Nueva grabación</button><p className="eyebrow library-label">BIBLIOTECA · {items.length}</p><nav aria-label="Grabaciones">{items.map(item=><button aria-current={selected===item.id?'page':undefined} className={`recording-item ${selected===item.id?'selected':''}`} key={item.id} onClick={()=>navigate(item.id)}><strong>{item.title}</strong><span>{kinds[item.kind]} · {formatTime(item.duration_ms)}</span><small>{statuses[item.status]||item.status}</small></button>)}{!items.length&&<p className="empty">Tus grabaciones aparecerán aquí.</p>}</nav><footer>Piloto privado · v0.1<br/>Contenido en español</footer></aside><main>{error&&<p role="alert" className="error">No se pudo conectar con el servidor: {error} <button onClick={()=>{setError('');refresh()}}>Reintentar</button></p>}{selected?<Workspace key={selected} id={selected} onChange={refresh} onDirty={setDirty} onDeleted={()=>{setSelected(null);setDirty(false);refresh()}}/>:<Upload onCreated={item=>{refresh();setSelected(item.id)}}/>}</main></div>
}
