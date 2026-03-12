import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  define: {
    'process.env': {}
  },
  server: {
    proxy: {
      '/api': 'http://localhost:4000'
    }
  }
});