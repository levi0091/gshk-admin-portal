import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    css: false,
    // e2e/ is Playwright, not Vitest: those specs drive a real browser against
    // a running stack and the live Companies Registry. Vitest collects any
    // *.spec.js it can see, so without this they fail in `npm test` and in CI
    // for reasons that have nothing to do with the code.
    include: ['src/**/*.{test,spec}.{js,jsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
})
