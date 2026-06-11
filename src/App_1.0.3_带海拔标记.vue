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
      polylines: [],
      chart: null,
      altitudeTexts: [],  // 添加海拔文本标记数组
      legendValues: { 'Loss Rate': '-', Ping: '-', Dist: '-', Altitude: '-' },
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
      // 过滤掉无效的经纬度数据
      this.points = parsed.data.filter(p => 
        p.Latitude != null && p.Longitude != null && 
        p['Altitude(m)'] != null &&
        !isNaN(p.Latitude) && !isNaN(p.Longitude) && !isNaN(p['Altitude(m)']) &&
        p.Latitude >= -90 && p.Latitude <= 90 &&
        p.Longitude >= -180 && p.Longitude <= 180 &&
        p['Altitude(m)'] >= 0
      );
      this.currentIndex = 0;
      if (this.points.length > 0) {
        this.drawTrack();
        this.initChart();
      } else {
        alert('没有有效的轨迹数据');
      }
    },
    drawTrack() {
      if (this.points.length === 0) return;
      
      const path = this.points.map(p => [p.Longitude, p.Latitude]);
      if (!this.map) {
        this.map = new AMap.Map(this.$refs.mapContainer, {
          viewMode: '3D',
          zoom: 15,
          pitch: 60,
          rotation: 0
        });
      }

      // 清除之前的多段线
      if (this.polylines) {
        this.polylines.forEach(poly => poly.setMap(null));
      }
      this.polylines = [];

      // 根据高度将路径分成段，每段用不同颜色
      const maxAlt = Math.max(...this.points.map(p => p['Altitude(m)']));
      const minAlt = Math.min(...this.points.map(p => p['Altitude(m)']));
      const segments = [];
      let currentSegment = [this.points[0]];

      for (let i = 1; i < this.points.length; i++) {
        const prev = this.points[i-1];
        const curr = this.points[i];
        if (Math.abs(curr['Altitude(m)'] - prev['Altitude(m)']) > 1) { // 如果高度变化超过1m，分段
          segments.push(currentSegment);
          currentSegment = [curr];
        } else {
          currentSegment.push(curr);
        }
      }
      segments.push(currentSegment);

      // 为每个段创建Polyline，用颜色表示高度
      segments.forEach(segment => {
        const avgAlt = segment.reduce((sum, p) => sum + p['Altitude(m)'], 0) / segment.length;
        const ratio = (avgAlt - minAlt) / (maxAlt - minAlt);
        const color = this.getColorFromAltitude(ratio);
        const segmentPath = segment.map(p => [p.Longitude, p.Latitude]);
        const polyline = new AMap.Polyline({
          path: segmentPath,
          strokeColor: color,
          strokeWeight: 4,
          showDir: false,
          geodesic: true
        });
        polyline.setMap(this.map);
        this.polylines.push(polyline);
      });

      // 清除之前的海拔文本标记
      this.altitudeTexts.forEach(text => text.setMap(null));
      this.altitudeTexts = [];

      // 每隔5个点添加一个海拔文本标记
      for (let i = 0; i < this.points.length; i += 5) {
        const p = this.points[i];
        const text = new AMap.Text({
          text: `${p['Altitude(m)'].toFixed(1)}m`,
          position: [p.Longitude, p.Latitude],
          style: {
            'background-color': 'rgba(255, 255, 255, 0.8)',
            'border': '1px solid #ccc',
            'padding': '2px 4px',
            'font-size': '12px',
            'color': '#333'
          },
          offset: new AMap.Pixel(0, -20)
        });
        text.setMap(this.map);
        this.altitudeTexts.push(text);
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
          position: [path[0][0], path[0][1]],
          icon,
          offset: new AMap.Pixel(-16, -16),
          rotation: 0
        });
        this.marker.setMap(this.map);
      } else {
        this.marker.setPosition([path[0][0], path[0][1]]);
      }
      this.map.setCenter([path[0][0], path[0][1]]);
      this.map.setFitView([...this.polylines, this.marker]);
    },
    getColorFromAltitude(ratio) {
      // 从蓝色（低海拔）到红色（高海拔）
      const r = Math.floor(255 * ratio);
      const g = Math.floor(255 * (1 - ratio));
      const b = Math.floor(255 * (1 - ratio));
      return `rgb(${r}, ${g}, ${b})`;
    },
    updatePosition(index) {
      if (!this.points[index] || !this.marker) return;
      const p = this.points[index];
      const pos = [p.Longitude, p.Latitude];
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
        const loss = this.points.map(p => p['Loss_Rate(%)'] || p['HB_Loss_Rate(%)'] || 0);
        const ping = this.points.map(p => p['Avg_Ping(ms)']);
        const dist = this.points.map(p => p['Dist_to_Arm_Pt(m)']);
        const altitude = this.points.map(p => p['Altitude(m)']);
        const names = ['Loss Rate', 'Ping', 'Dist', 'Altitude'];
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
          yAxis: [
            { type: 'value', name: '% / ms / m' },
            { type: 'value', name: 'Altitude (m)', position: 'right' }
          ],
          series: [
            { name: 'Loss Rate', type: 'line', data: loss },
            { name: 'Ping', type: 'line', data: ping },
            { name: 'Dist', type: 'line', data: dist },
            { name: 'Altitude', type: 'line', data: altitude, yAxisIndex: 1 }
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
      const point = this.points[idx] || {};
      this.legendValues['Loss Rate'] = (point['Loss_Rate(%)'] || point['HB_Loss_Rate(%)']) != null ? `${point['Loss_Rate(%)'] || point['HB_Loss_Rate(%)']}%` : '-';
      this.legendValues['Ping'] = point['Avg_Ping(ms)'] != null ? `${point['Avg_Ping(ms)']}ms` : '-';
      this.legendValues['Dist'] = point['Dist_to_Arm_Pt(m)'] != null ? `${point['Dist_to_Arm_Pt(m)']}m` : '-';
      this.legendValues['Altitude'] = point['Altitude(m)'] != null ? `${point['Altitude(m)']}m` : '-';
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
