import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // MapLibre GL ships its own web worker bundle; Vite's dep-optimizer
    // cannot pre-bundle it and emits a harmless-but-noisy warning each
    // request. Excluding it silences the log without affecting runtime.
    exclude: ['maplibre-gl'],
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy /api/* and /ws/* to the FastAPI backend so the frontend
      // never has to hardcode the API URL in non-demo mode.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
