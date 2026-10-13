import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Builds into the Python package so `lab ui` serves it without Node.
// `npm run dev` proxies the API to a running `uv run lab ui` (port 8765).
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../lab/viewer/static', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } } },
  css: { modules: { localsConvention: 'camelCaseOnly' } },
})
