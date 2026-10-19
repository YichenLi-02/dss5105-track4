import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the browser talks to Vite; /api is proxied to the single FastAPI process.
// No key, token or vault path is ever exposed through VITE_* variables.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
})
