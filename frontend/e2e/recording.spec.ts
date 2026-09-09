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
