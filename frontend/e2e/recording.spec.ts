import { test, expect } from '@playwright/test'

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
    await page.getByRole('button',{name:'Añadir hablante',exact:true}).click()
    await page.getByLabel('Hablante 1',{exact:true}).fill('Ana')
    await page.getByRole('button',{name:'Añadir segmento en este momento'}).click()
    await page.getByRole('textbox',{name:'Texto',exact:true}).fill('Una intervención revisada.')
    await page.getByRole('combobox',{name:'Hablante',exact:true}).selectOption({label:'Ana'})
    await page.getByRole('button',{name:'Guardar revisión'}).click()
    await expect(page.getByRole('status')).toHaveText('Revisión guardada.')
    await page.reload()
    await page.getByRole('button',{name:new RegExp(title)}).click()
    await expect(page.getByRole('textbox',{name:'Texto',exact:true})).toHaveValue('Una intervención revisada.')
    await expect(page.getByLabel('Hablante 1',{exact:true})).toHaveValue('Ana')
    await page.screenshot({path:test.info().outputPath('workspace.png'),fullPage:true})
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
    await page.screenshot({path:test.info().outputPath('mobile.png'),fullPage:true})
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
    const claim={id:'claim-1',status:'proposed',revision:0,normalized_text:'Júpiter es grande.',original_quote:'Júpiter es grande',category:'fact',verifiable:true,start_ms:0,end_ms:900,ambiguity_notes:['Falta la magnitud'],missing_context:['Comparación'],segments:[{segment_id:'s1',start_ms:0,end_ms:900,speaker_id:'a',speaker_name:'Ana',position:0}]}
    const run={id:'run-1',recording_id:recording.id,recording_revision:2,kind:'claim_extraction',status:'completed',provider:'openrouter',model:'modelo-gratuito',prompt_version:'claims-v1',usage:{total_tokens:21},error:null,unreviewed_segment_count:2,created_at:'2026-09-09T00:00:00',completed_at:'2026-09-09T00:00:01',claims:[claim]}
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
      await route.fulfill({json:{...claim,...body,status:'edited',revision:1,start_ms:1000,end_ms:1500,segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}]}})
    })
    await page.route('**/api/claims/claim-1/accept',async route=>{
      expect(route.request().postDataJSON()).toEqual({revision:1})
      await route.fulfill({json:{...claim,normalized_text:'Júpiter tiene lunas.',status:'accepted',revision:2,start_ms:1000,end_ms:1500,segments:[{segment_id:'s2',start_ms:1000,end_ms:1500,speaker_id:'b',speaker_name:'Beto',position:0}]}})
    })

    await page.goto('/')
    await page.getByRole('button',{name:new RegExp(title)}).click()
    page.once('dialog',dialog=>{expect(dialog.message()).toContain('sin revisión manual');dialog.accept()})
    await page.getByRole('button',{name:'Extraer afirmaciones'}).click()
    await expect(page.getByText(/2 segmentos sin revisión manual/)).toBeVisible()
    await expect(page.getByRole('blockquote')).toHaveText('Júpiter es grande')
    await expect(page.getByText('Falta la magnitud')).toBeVisible()
    await expect(page.getByText('Comparación')).toBeVisible()
    await page.getByRole('button',{name:'Editar'}).click()
    await page.getByRole('textbox',{name:'Texto normalizado'}).fill('Júpiter tiene lunas.')
    await page.getByLabel(/00:01 · y tiene lunas/).check()
    await page.getByLabel(/00:00 · Júpiter es grande/).uncheck()
    await page.getByRole('button',{name:'Guardar candidata'}).click()
    await expect(page.locator('.claim-speaker')).toHaveText('Beto')
    await page.getByRole('button',{name:'Aceptar'}).click()
    await expect(page.locator('.claim-card .badge')).toHaveText('Aceptada')
    await page.getByRole('button',{name:/00:01–00:01 ↗/}).click()
    await expect.poll(()=>page.locator('video').evaluate((video:HTMLVideoElement)=>video.currentTime)).toBe(1)
    await page.getByRole('button',{name:'Editar'}).click()
    await page.getByRole('textbox',{name:'Texto normalizado'}).fill('Cambio sin guardar')
    const dialogPromise=page.waitForEvent('dialog')
    const navigation=page.getByRole('button',{name:'Nueva grabación'}).click()
    const dialog=await dialogPromise
    expect(dialog.message()).toContain('sin guardar')
    await dialog.dismiss()
    await navigation
    await page.getByRole('button',{name:'Cancelar edición'}).click()

    await page.getByRole('textbox',{name:'Texto',exact:true}).first().fill('Júpiter es enorme')
    await page.getByRole('button',{name:'Guardar revisión'}).click()
    await expect(page.getByText(/extracción está desactualizada/)).toBeVisible()
    await expect(page.locator('.claim-card').getByRole('button',{name:'Editar'})).toBeDisabled()
    await page.setViewportSize({width:390,height:844})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)

  }finally{
    await request.delete(base).catch(()=>{})
  }
})
