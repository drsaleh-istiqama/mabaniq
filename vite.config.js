// Unit 3 — the web sources in web/ are built into frontend/dist and served by FastAPI under /static (hashed, immutable assets).
import {resolve} from 'node:path';
import {defineConfig} from 'vite';

export default defineConfig({
  root: 'web',
  base: '/static/',
  publicDir: false,
  build: {
    outDir: resolve(__dirname, 'frontend/dist'),
    emptyOutDir: true,
    sourcemap: false,
    target: 'es2022',
    modulePreload: {polyfill: false},
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'web/index.html'),
        login: resolve(__dirname, 'web/login.html'),
        client: resolve(__dirname, 'web/client.html'),
        broker: resolve(__dirname, 'web/broker.html'),
        landing: resolve(__dirname, 'web/landing.html'),        // 0.14.0: public landing page (Arabic, served on /)
        'landing-en': resolve(__dirname, 'web/landing-en.html'),  // 0.14.0: English twin (served on /en)
      },
    },
  },
  server: {
    port: 5173,
    proxy: {'/api': 'http://127.0.0.1:8800'},
  },
});
