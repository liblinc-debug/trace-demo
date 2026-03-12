import { createApp } from 'vue';
import App from './App.vue';

// inject amap script dynamically
function loadAmap(key) {
  return new Promise((resolve, reject) => {
    if (window.AMap) return resolve(window.AMap);
    const script = document.createElement('script');
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}`;
    script.onload = () => resolve(window.AMap);
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

const key = import.meta.env.VITE_AMAP_KEY || '';
loadAmap(key).then(() => {
  createApp(App).mount('#app');
}).catch(err => {
  console.error('failed to load amap', err);
  createApp(App).mount('#app');
});
