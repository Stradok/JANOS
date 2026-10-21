import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  build: {outDir: '../../jarvis-core/janos/ui_dist', emptyOutDir: true},
  server: {proxy: {'/health': 'http://127.0.0.1:8000', '/telemetry': 'http://127.0.0.1:8000',
    '/chat': 'http://127.0.0.1:8000', '/speak': 'http://127.0.0.1:8000'}},
});
