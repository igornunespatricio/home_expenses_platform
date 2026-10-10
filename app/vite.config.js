import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Local dev: set VITE_DEV_PROXY_TARGET to the deployed CloudFront URL
// (e.g. https://d111111abcdef8.cloudfront.net) so /api/* reaches the real API.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.VITE_DEV_PROXY_TARGET

  return {
    plugins: [react()],
    server: target
      ? { proxy: { '/api': { target, changeOrigin: true, secure: true } } }
      : {},
  }
})
