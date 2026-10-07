/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': '/src' } },
  server: {
    // Same-origin in dev, so the httpOnly refresh cookie behaves exactly as it does behind nginx.
    proxy: { '/api': backend, '/ws': { target: backend, ws: true } },
  },
  build: { chunkSizeWarningLimit: 900 },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts', css: false },
})
