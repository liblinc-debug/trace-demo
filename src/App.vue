<template>
  <div class="app-container">
    <h1>无人机轨迹回放</h1>
    <div class="controls">
      <select v-model="selectedFile" @change="onFileChange">
        <option value="" disabled>请选择飞行记录...</option>
        <option v-for="f in files" :key="f" :value="f">{{ f }}</option>
      </select>
      <button @click="play" :disabled="!canPlay">播放</button>
      <button @click="pause" :disabled="!isPlaying">暂停</button>
      <input type="range" min="0" :max="points.length-1" v-model.number="currentIndex" @input="onSliderChange" />
    </div>
    <div class="map" ref="mapContainer"></div>
    <div class="chart" ref="chartContainer"></div>
  </div>
</template>

<script>
import axios from 'axios';
import Papa from 'papaparse';
import * as echarts from 'echarts';

export default {
  data() {
    return {
      files: [],
      selectedFile: '',
      points: [],
      currentIndex: 0,
      isPlaying: false,
      timer: null,
      map: null,
      marker: null,
      polyline: null,
      chart: null,
    };
  },
  computed: {
    canPlay() {
      return this.points.length > 0 && !this.isPlaying;
    }
  },
  methods: {
    async fetchFiles() {
      const res = await axios.get('/api/logs');
      this.files = res.data;
    },
    async onFileChange() {
      if (!this.selectedFile) return;
      const res = await axios.get(`/api/logs/${encodeURIComponent(this.selectedFile)}`);
      const text = res.data;
      const parsed = Papa.parse(text, { header: true, dynamicTyping: true });
      this.points = parsed.data;
      this.currentIndex = 0;
      this.drawTrack();
      this.initChart();
    },
    drawTrack() {
      const path = this.points.map(p => [p.Longitude, p.Latitude, p['Altitude(m)']]);
      if (!this.map) {
        this.map = new AMap.Map(this.$refs.mapContainer, {
          viewMode: '3D',
          zoom: 15
        });
      }
      if (this.polyline) {
        this.polyline.setPath(path);
      } else {
        this.polyline = new AMap.Polyline({
          path,
          strokeColor: '#7ec0ee',
          strokeWeight: 3,
          showDir: false
        });
        this.polyline.setMap(this.map);
      }
      const icon = new AMap.Icon({
        image: 'https://cdn-icons-png.flaticon.com/512/1384/1384060.png',
        size: new AMap.Size(32, 32),
        anchor: 'center'
      });
      if (!this.marker) {
        this.marker = new AMap.Marker({
          position: path[0],
          icon,
          offset: new AMap.Pixel(-16, -16)
        });
        this.marker.setMap(this.map);
      } else {
        this.marker.setPosition(path[0]);
      }
      this.map.setCenter(path[0]);
    },
    updatePosition(index) {
      if (!this.points[index]) return;
      const p = this.points[index];
      const pos = [p.Longitude, p.Latitude, p['Altitude(m)']];
      this.marker.setPosition(pos);
      this.map.setCenter(pos);
      // update chart pointer
      this.updateChartPointer(index);
    },
    play() {
      if (this.isPlaying) return;
      this.isPlaying = true;
      this.timer = setInterval(() => {
        if (this.currentIndex < this.points.length - 1) {
          this.currentIndex++;
          this.updatePosition(this.currentIndex);
        } else {
          this.pause();
        }
      }, 200);
    },
    pause() {
      this.isPlaying = false;
      clearInterval(this.timer);
      this.timer = null;
    },
    onSliderChange() {
      this.updatePosition(this.currentIndex);
    },
    initChart() {
      this.$nextTick(() => {
        if (!this.chart) {
          this.chart = echarts.init(this.$refs.chartContainer);
        }
        const times = this.points.map(p => p.Timestamp);
        const loss = this.points.map(p => p['Loss_Rate(%)']);
        const ping = this.points.map(p => p['Avg_Ping(ms)']);
        const dist = this.points.map(p => p['Dist_to_Arm_Pt(m)']);
        const option = {
          tooltip: { trigger: 'axis' },
          xAxis: { type: 'category', data: times },
          yAxis: [{ type: 'value', name: '% / ms / m' }],
          series: [
            { name: 'Loss Rate', type: 'line', data: loss },
            { name: 'Ping', type: 'line', data: ping },
            { name: 'Dist', type: 'line', data: dist }
          ],
          axisPointer: {
            show: true,
            type: 'line',
            snap: true
          }
        };
        this.chart.setOption(option);
      });
    },
    updateChartPointer(idx) {
      if (!this.chart) return;
      this.chart.dispatchAction({
        type: 'updateAxisPointer',
        xAxisIndex: 0,
        seriesIndex: 0,
        dataIndex: idx
      });
    }
  },
  mounted() {
    this.fetchFiles();
    window.addEventListener('beforeunload', () => {
      if (this.timer) clearInterval(this.timer);
    });
  }
};
</script>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
}
.map {
  flex: 1;
}
.chart {
  height: 200px;
}
</style>
