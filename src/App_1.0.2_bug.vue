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
      legendValues: { 'Loss Rate': '-', Ping: '-', Dist: '-' }
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
    //   const icon = new AMap.Icon({
    //     image: 'https://cdn-icons-png.flaticon.com/512/1384/1384060.png',
    //     size: new AMap.Size(32, 32),
    //     anchor: 'center'
    //   });

    const icon = new AMap.Icon({
        image: 'data:image/svg+xml;base64,' + btoa(`
          <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">
            <circle cx="16" cy="16" r="12" fill="#007aff" stroke="#fff" stroke-width="2" />
          </svg>
        `),
        size: new AMap.Size(32, 32),
        anchor: 'center'
      });


      if (!this.marker) {
        this.marker = new AMap.Marker({
          position: path[0],
          icon,
          offset: new AMap.Pixel(-16, -16),
          rotation: 0
        });
        this.marker.setMap(this.map);
      } else {
        this.marker.setPosition(path[0]);
      }
      this.map.setCenter(path[0]);
      this.map.setFitView([this.polyline, this.marker]);
    },
    updatePosition(index) {
      if (!this.points[index]) return;
      const p = this.points[index];
      const pos = [p.Longitude, p.Latitude, p['Altitude(m)']];
      this.marker.setPosition(pos);
      if (p.Heading !== undefined) {
        this.marker.setRotation(p.Heading);
      }
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
        const loss = this.points.map(p => p.loss);
        const ping = this.points.map(p => p.ping);
        const dist = this.points.map(p => p.dist);
        const names = ['Loss Rate', 'Ping', 'Dist'];
        const option = {
          legend: {
            data: names,
            top: 0,
            formatter: name => `${name}: ${this.legendValues[name]}`
          },
          tooltip: {
            trigger: 'axis',
            formatter: params => {
              if (!params || params.length === 0) return '';
              const time = params[0].axisValue;
              let text = `<b>${time}</b><br/>`;
              params.forEach(p => {
                text += `${p.marker} ${p.seriesName}: ${p.data}<br/>`;
              });
              return text;
            }
          },
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
            lineStyle: { color: '#888', width: 1 },
            snap: true
          }
        };
        this.chart.setOption(option);
      });
    },
    updateChartPointer(idx) {
      if (!this.chart) return;
      // move axis pointer and show tooltip at current index
      this.chart.dispatchAction({
        type: 'updateAxisPointer',
        xAxisIndex: 0,
        dataIndex: idx
      });
      this.chart.dispatchAction({
        type: 'showTip',
        seriesIndex: 0,
        dataIndex: idx
      });
      // update legendValues and refresh formatter
      const point = this.points[idx] || {};
      this.legendValues['Loss Rate'] = point.loss != null ? `${point.loss}%` : '-';
      this.legendValues['Ping'] = point.ping != null ? `${point.ping}ms` : '-';
      this.legendValues['Dist'] = point.dist != null ? `${point.dist}m` : '-';
      this.chart.setOption({});
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
  background: #f5f5f5;
}
.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #ddd;
}
h1 {
  text-align: center;
  margin: 12px 0;
  color: #333;
  font-size: 1.5em;
}
.controls select,
.controls button,
.controls input[type="range"] {
  font-size: 1em;
}
.map {
  flex: 1;
  border: 1px solid #ccc;
}
.chart {
  height: 200px;
  border-top: 1px solid #ddd;
  background: #fff;
}
</style>
