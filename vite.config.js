import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  const backendPort = Number(env.PORT) || 4000;

  return {
    //base: '/uav-logs/',
    plugins: [vue()],
    define: {
      'process.env': {}
    },
    server: {
      host: env.VITE_HOST || '0.0.0.0',
      port: Number(env.VITE_PORT) || 5173,
      proxy: {
        '/api': `http://127.0.0.1:${backendPort}`
      }
    }
  };
});
