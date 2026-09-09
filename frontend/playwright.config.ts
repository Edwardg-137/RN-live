import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: {baseURL:'http://127.0.0.1:8080', channel:'msedge', headless:true, actionTimeout:8000, trace:'retain-on-failure'},
})
