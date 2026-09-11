import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

function wav(){
  const bytes=Buffer.alloc(44+64000)
  bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8)
  bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(1,20);bytes.writeUInt16LE(1,22)
  bytes.writeUInt32LE(16000,24);bytes.writeUInt32LE(32000,28);bytes.writeUInt16LE(2,32);bytes.writeUInt16LE(16,34)
  bytes.write('data',36);bytes.writeUInt32LE(64000,40)
  return bytes
}

test('subir, revisar, recargar y eliminar una grabación real',async({page,request})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  const title=`Prueba navegador ${Date.now()}`
  let recordingId:string|undefined
  try {
    await page.goto('/')
    await page.getByLabel('Archivo de audio o video').setInputFiles({name:'test.wav',mimeType:'audio/wav',buffer:wav()})
    await page.getByLabel('Título',{exact:true}).fill(title)
    await page.getByLabel('Tipo de contenido').selectOption('interview')
    await page.getByRole('button',{name:'Crear grabación'}).click()
    await expect(page.getByRole('heading',{name:title})).toBeVisible()
    const records=await (await request.get('/api/recordings')).json()
    recordingId=records.find((r:{title:string})=>r.title===title).id
    const speakersToggle=page.getByRole('button',{name:/Identificar hablantes/})
    const transcriptToggle=page.getByRole('button',{name:/Editar transcripción/})
    await expect(page.getByRole('button',{name:'Descargar JSON'})).toBeDisabled()
    await expect(speakersToggle).toHaveAttribute('aria-expanded','false')
    await expect(transcriptToggle).toHaveAttribute('aria-expanded','false')
    await speakersToggle.click()
    await page.getByRole('button',{name:'Añadir hablante',exact:true}).click()
    await page.getByLabel('Hablante 1',{exact:true}).fill('Ana')
    await transcriptToggle.click()
    await page.getByRole('button',{name:'Añadir segmento en este momento'}).click()
    await page.getByRole('textbox',{name:'Texto',exact:true}).fill('Una intervención revisada.')
    await page.getByRole('combobox',{name:'Hablante',exact:true}).selectOption({label:'Ana'})
    await page.getByRole('button',{name:'Cerrar editor'}).click()
    await expect(transcriptToggle).toBeFocused()
    await expect(transcriptToggle).toContainText('Cambios pendientes')
    await page.getByRole('button',{name:'Guardar revisión'}).click()
    await expect(page.getByRole('status')).toHaveText('Revisión guardada.')
    await page.reload()
    await page.getByRole('button',{name:new RegExp(title)}).click()
    await page.getByRole('button',{name:/Editar transcripción/}).click()
    await expect(page.getByRole('textbox',{name:'Texto',exact:true})).toHaveValue('Una intervención revisada.')
    await page.getByRole('button',{name:'Cerrar editor'}).click()
    await page.getByRole('button',{name:/Identificar hablantes/}).click()
    await expect(page.getByLabel('Hablante 1',{exact:true})).toHaveValue('Ana')
    await page.getByRole('button',{name:'Cerrar editor'}).click()
    await page.screenshot({path:test.info().outputPath('workspace.png'),fullPage:true})
    await page.getByRole('button',{name:/Editar transcripción/}).click()
    await page.getByRole('textbox',{name:'Texto',exact:true}).fill('Cambio sin guardar')
    await page.getByRole('button',{name:new RegExp(title)}).click()
    const dialogPromise=page.waitForEvent('dialog')
    const navigation=page.getByRole('button',{name:'Nueva grabación'}).click()
    const dialog=await dialogPromise
    expect(dialog.message()).toContain('sin guardar')
    await dialog.dismiss()
    await navigation
    await expect(page.getByRole('textbox',{name:'Texto',exact:true})).toHaveValue('Cambio sin guardar')
    await page.getByRole('button',{name:'00:00 ↗'}).click()
    await expect.poll(()=>page.locator('video').evaluate((v:HTMLVideoElement)=>v.currentTime)).toBe(0)
    await page.setViewportSize({width:390,height:844})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await expect(page.locator('#secondary-editor')).toHaveCSS('position','fixed')
    await page.screenshot({path:test.info().outputPath('mobile.png'),fullPage:true})
    await page.getByRole('button',{name:'Cerrar editor'}).click()
    page.once('dialog',dialog=>dialog.accept())
    await page.getByRole('button',{name:'Eliminar',exact:true}).click()
    await expect(page.getByRole('heading',{name:'Nueva grabación'})).toBeVisible()
    expect(errors).toEqual([])
  } finally {
    if(recordingId)await request.delete(`/api/recordings/${recordingId}`).catch(()=>{})
  }
})

test('revisar, editar y aceptar candidatas con una respuesta simulada',async({page,request})=>{
  const title=`Afirmaciones ${Date.now()}`
  const created=await request.post('/api/recordings',{multipart:{
    file:{name:'claims.wav',mimeType:'audio/wav',buffer:wav()},title,kind:'interview',speaker_count:'2',scope:''
  }})
  expect(created.ok()).toBe(true)
  const recording=await created.json()
  const base=`/api/recordings/${recording.id}`
  try{
    expect((await request.put(base+'/speakers',{data:{revision:0,speakers:[{id:'a',name:'Ana'},{id:'b',name:'Beto'}]}})).ok()).toBe(true)
    expect((await request.put(base+'/segments',{data:{revision:1,segments:[
      {id:'s1',start_ms:0,end_ms:900,text:'Júpiter es grande',speaker_id:'a'},
      {id:'s2',start_ms:1000,end_ms:1500,text:'y tiene lunas',speaker_id:'b'},
    ]}})).ok()).toBe(true)
    const claim={id:'claim-1',status:'proposed',revision:0,normalized_text:'Júpiter es grande.',original_quote:'Júpiter es grande',category:'fact',verifiable:true,start_ms:0,end_ms:900,ambiguity_notes:['Falta la magnitud'],missing_context:['Comparación'],conversation_relation:'answer',context_required:true,standalone_text:'Ana afirmó que Júpiter es grande.',segments:[{segment_id:'s1',start_ms:0,end_ms:900,speaker_id:'a',speaker_name:'Ana',position:0}],context_segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}]}
    const secondClaim={...claim,id:'claim-2',normalized_text:'Saturno tiene anillos.',standalone_text:'Saturno tiene anillos.',original_quote:'Saturno tiene anillos',category:'opinion' as const,start_ms:1000,end_ms:1500,ambiguity_notes:[],missing_context:[],conversation_relation:'standalone',context_required:false,segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}],context_segments:[]}
    const run={id:'run-1',recording_id:recording.id,recording_revision:2,kind:'claim_extraction',status:'completed',provider:'openrouter',model:'modelo-gratuito',prompt_version:'claims-v2-conversation',usage:{total_tokens:21},error:null,unreviewed_segment_count:2,created_at:'2026-09-09T00:00:00',completed_at:'2026-09-09T00:00:01',claims:[claim,secondClaim]}
    await page.route(`**${base}`,async route=>{
      if(route.request().method()==='GET'){
        const response=await route.fetch()
        const snapshot=await response.json()
        snapshot.segments=snapshot.segments.map((segment:{reviewed:boolean})=>({...segment,reviewed:false}))
        await route.fulfill({response,json:snapshot})
      }else await route.continue()
    })
    let transcriptChanged=false
    await page.route(`**${base}/segments`,async route=>{
      if(route.request().method()==='PUT')transcriptChanged=true
      await route.continue()
    })
    await page.route(`**${base}/claim-extraction`,async route=>{
      if(route.request().method()==='POST')await route.fulfill({json:run})
      else await route.fulfill({json:transcriptChanged?{...run,status:'stale',error:'La revisión del transcript cambió'}:run})
    })
    await page.route('**/api/claims/claim-1',async route=>{
      const body=route.request().postDataJSON()
      expect(body).toEqual({revision:0,normalized_text:'Júpiter tiene lunas.',category:'fact',segment_ids:['s2']})
      await route.fulfill({json:{...claim,...body,standalone_text:body.normalized_text,status:'edited',revision:1,start_ms:1000,end_ms:1500,segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}]}})
    })
    await page.route('**/api/claims/claim-1/accept',async route=>{
      expect(route.request().postDataJSON()).toEqual({revision:1})
      await route.fulfill({json:{...claim,normalized_text:'Júpiter tiene lunas.',standalone_text:'Júpiter tiene lunas.',status:'accepted',revision:2,start_ms:1000,end_ms:1500,segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}]}})
    })

    await page.goto('/')
    await page.getByRole('button',{name:new RegExp(title)}).click()
    page.once('dialog',dialog=>{expect(dialog.message()).toContain('sin revisión manual');dialog.accept()})
    await page.getByRole('button',{name:'Extraer afirmaciones'}).click()
    await expect(page.getByText(/2 segmentos sin revisión manual/)).toBeVisible()
    await expect(page.getByText(/Categorías: Hecho 1 · Opinión 1/)).toBeVisible()
    await expect(page.getByRole('blockquote').first()).toHaveText('Júpiter es grande')
    await expect(page.getByText('Falta la magnitud')).toBeVisible()
    await expect(page.getByText('Comparación')).toBeVisible()
    await page.getByText(/Contexto usado/).click()
    await page.getByRole('button',{name:/00:01 · Beto/}).click()
    await expect.poll(()=>page.locator('video').evaluate((video:HTMLVideoElement)=>video.currentTime)).toBe(1)
    const carousel=page.getByRole('list',{name:'Carrusel de afirmaciones'})
    await expect(page.getByText('1 de 2')).toBeVisible()
    await carousel.focus()
    await carousel.press('ArrowRight')
    await expect(page.getByText('2 de 2')).toBeVisible()
    await page.getByRole('button',{name:'Afirmación anterior'}).click()
    await expect(page.getByText('1 de 2')).toBeVisible()
    await page.getByRole('button',{name:'Editar'}).first().click()
    await page.getByRole('textbox',{name:'Texto normalizado'}).fill('Júpiter tiene lunas.')
    await page.getByLabel(/00:01 · y tiene lunas/).check()
    await page.getByLabel(/00:00 · Júpiter es grande/).uncheck()
    await page.getByRole('button',{name:'Guardar candidata'}).click()
    await expect(page.locator('.claim-speaker').first()).toHaveText('Beto')
    await page.getByRole('button',{name:'Aceptar'}).first().click()
    await expect(page.locator('.claim-card .badge').first()).toHaveText('Aceptada')
    await page.getByRole('button',{name:/00:01–00:01 ↗/}).first().click()
    await expect.poll(()=>page.locator('video').evaluate((video:HTMLVideoElement)=>video.currentTime)).toBe(1)
    await page.getByRole('button',{name:'Editar'}).first().click()
    await page.getByRole('textbox',{name:'Texto normalizado'}).fill('Cambio sin guardar')
    page.once('dialog',dialog=>{expect(dialog.message()).toContain('transcripción completa');dialog.accept()})
    const downloadPromise=page.waitForEvent('download')
    await page.getByRole('button',{name:'Descargar JSON'}).click()
    const download=await downloadPromise
    expect(download.suggestedFilename()).toMatch(/^afirmaciones-\d+-revision-2\.json$/)
    const downloadPath=await download.path()
    const exported=JSON.parse(await readFile(downloadPath!,'utf8'))
    expect(exported.schema_version).toBe('rn-live-export-v1')
    expect(exported.export_state.contains_unsaved_changes).toBe(true)
    expect(exported.analysis.claims[0].normalized_text).toBe('Cambio sin guardar')
    expect(exported.recording.filename).toBeUndefined()
    const dialogPromise=page.waitForEvent('dialog')
    const navigation=page.getByRole('button',{name:'Nueva grabación'}).click()
    const dialog=await dialogPromise
    expect(dialog.message()).toContain('sin guardar')
    await dialog.dismiss()
    await navigation
    await page.getByRole('button',{name:'Cancelar edición'}).click()

    await page.getByRole('button',{name:/Editar transcripción/}).click()
    await page.getByRole('textbox',{name:'Texto',exact:true}).first().fill('Júpiter es enorme')
    await page.getByRole('button',{name:'Cerrar editor'}).click()
    await page.getByRole('button',{name:'Guardar revisión'}).click()
    await expect(page.getByText(/extracción está desactualizada/)).toBeVisible()
    await expect(page.locator('.claim-card').getByRole('button',{name:'Editar'}).first()).toBeDisabled()
    await page.setViewportSize({width:390,height:844})
    await expect(page.getByRole('button',{name:'Descargar JSON'})).toBeVisible()
    await expect(page.locator('#secondary-editor')).toBeHidden()
    page.once('dialog',dialog=>dialog.accept())
    const mobileDownloadPromise=page.waitForEvent('download')
    await page.getByRole('button',{name:'Descargar JSON'}).click()
    const mobileDownload=await mobileDownloadPromise
    expect(JSON.parse(await readFile((await mobileDownload.path())!,'utf8')).schema_version).toBe('rn-live-export-v1')
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)

  }finally{
    await request.delete(base).catch(()=>{})
  }
})
