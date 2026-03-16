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
      locaContainer: null,
      locaLineLayer: null,
      polylines: [],
      chart: null,
      mapScriptLoaded: false,
      altitudeMarker: null,
      altitudeLabels: [],
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
      if (this.files && this.files.length > 0) {
        this.selectedFile = this.files[0];
        await this.onFileChange();
      }
    },
    loadAMapScript() {
      if (this.mapScriptLoaded && window.AMap) {
        return Promise.resolve();
      }
      if (this.loadingMapScript) {
        return this.loadingMapScript;
      }
      this.loadingMapScript = new Promise((resolve, reject) => {
        const amapKey = import.meta.env.VITE_AMAP_KEY || 'df08b9775f1b5949a902daf1696e6560';
        const securityJsCode = import.meta.env.VITE_AMAP_SECURITY || '3b542abbb6dde06fb6d0a6692089a30f';
        window._AMapSecurityConfig = { securityJsCode };

        const loadScript = (src) => new Promise((res, rej) => {
          const script = document.createElement('script');
          script.src = src;
          script.onload = res;
          script.onerror = (err) => rej(new Error('Script load failed: ' + src + ' - ' + err));
          document.head.appendChild(script);
        });

        Promise.all([
          loadScript(`https://webapi.amap.com/maps?v=2.0&key=${amapKey}&plugin=AMap.ControlBar,AMap.MoveAnimation,AMap.Scale`),
          loadScript(`https://webapi.amap.com/loca?v=2.0.0&key=${amapKey}`)
        ]).then(() => {
          this.mapScriptLoaded = true;
          resolve();
        }).catch(reject);
      }).finally(() => {
        this.loadingMapScript = null;
      });
      return this.loadingMapScript;
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
        try {
          await this.loadAMapScript();
          await this.drawTrack();
        } catch (err) {
          console.error('AMap 加载失败:', err);
          alert('地图脚本加载失败，请检查网络或 API Key。');
        }
        this.initChart();
      } else {
        alert('没有有效的轨迹数据');
      }
    },
    async drawTrack() {
      if (this.points.length === 0) return;
      if (!this.mapScriptLoaded && !window.AMap) {
        await this.loadAMapScript();
      }
      if (typeof AMap === 'undefined') {
        console.error('AMap 未定义');
        return;
      }

      // 转换为高德 GCJ02 坐标
      const convertedPoints = this.points.map(p => {
        const [lat, lon] = this.wgs84ToGcj02(p.Latitude, p.Longitude);
        return {
          ...p,
          Latitude: lat,
          Longitude: lon
        };
      });
      this.points = convertedPoints;
      
      // 创建路径
      const path = this.points.map(p => [p.Longitude, p.Latitude]);
      if (!this.map) {
        this.map = new AMap.Map(this.$refs.mapContainer, {
          viewMode: '3D',
          zoom: 15,
          center: path[0],
          pitch: 60,
          rotation: 0,
          layers: [new AMap.TileLayer.Satellite()]
        });
        // 增加视角导航与缩放控件
        this.map.addControl(new AMap.ControlBar({ position: 'RB' }));
        this.map.addControl(new AMap.Scale());
      } else {
        // 如果已有地图，确保设置卫星图层
        const layers = this.map.getLayers ? this.map.getLayers() : [];
        const hasSat = layers.some(l => l instanceof AMap.TileLayer.Satellite);
        if (!hasSat) {
          this.map.setLayers([new AMap.TileLayer.Satellite()]);
        }
      }

      // 清除之前的多段线或 Loca 图层
      if (this.polylines) {
        this.polylines.forEach(poly => poly.setMap(null));
      }
      this.polylines = [];
      if (this.locaLineLayer) {
        this.locaLineLayer.setMap(null);
        this.locaLineLayer = null;
      }
      if (this.locaContainer && typeof this.locaContainer.clear === 'function') {
        this.locaContainer.clear();
      }

      // 3D轨迹线数据 [lng, lat, altitude]
      const lineCoords = this.points.map(p => [p.Longitude, p.Latitude, p['Altitude(m)']]);
      const hasLoca = window.AMap && window.Loca && typeof window.Loca.Container === 'function';
      if (hasLoca) {
        if (!this.locaContainer) {
          this.locaContainer = new Loca.Container({ map: this.map });
        }
        const source = new Loca.GeoJSONSource({
          data: {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              geometry: {
                type: 'LineString',
                coordinates: lineCoords
              },
              properties: {}
            }]
          }
        });
        this.locaLineLayer = new Loca.LineLayer({
          zIndex: 30,
          lineWidth: 1.0,
          opacity: 0.55
        });
        this.locaLineLayer.setSource(source, {
          height: (index, feature) => feature.geometry.coordinates[index][2],
          color: '#ffa500'
        });
        this.locaContainer.add(this.locaLineLayer);
      } else {
        const polyline = new AMap.Polyline({
          path: lineCoords,
          enableAltitude: true,
          strokeColor: '#ffa500',
          strokeWeight: 4,
          showDir: false,
          geodesic: true
        });
        polyline.setMap(this.map);
        this.polylines.push(polyline);
      }

      // 使用 AMap.Text 可能在当前版本无实现，改为仅路线与标记。
      if (this.altitudeLabels && this.altitudeLabels.length > 0) {
        this.altitudeLabels.forEach(label => label.setMap(null));
      }
      this.altitudeLabels = [];
    //   const icon = new AMap.Icon({
    //     image: 'https://cdn-icons-png.flaticon.com/512/1384/1384060.png',
    //     size: new AMap.Size(32, 32),
    //     anchor: 'center'
    //   });

    // const icon = new AMap.Icon({
    //     image: 'data:image/svg+xml;base64,' + btoa(`
    //       <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    //         <polygon points="16,4 28,28 4,28" fill="#ff5f1f" stroke="#fff" stroke-width="2"/>
    //       </svg>
    //     `),
    //     size: new AMap.Size(32, 32),
    //     anchor: 'center'
    //   });
    const icon = new AMap.Icon({
        image: 'http://qh.airsensor.top:7200/img/mobile_online.acd05a0a.svg',
        size: new AMap.Size(32, 32),
        anchor: 'center'
      });

      const initialHeading = this.points[0].Heading != null ? this.points[0].Heading : 0;
      const adjustedInitialHeading = this.getMarkerHeading(initialHeading);
      if (!this.marker) {
        this.marker = new AMap.Marker({
          position: [path[0][0], path[0][1], this.points[0]['Altitude(m)']],
          icon,
          offset: new AMap.Pixel(-16, -16)
        });
        this.marker.setMap(this.map);
      } else {
        this.marker.setPosition([path[0][0], path[0][1], this.points[0]['Altitude(m)']]);
      }
      this.applyMarkerHeading(this.marker, adjustedInitialHeading);
      this.map.setCenter([path[0][0], path[0][1]]);
      this.map.setFitView([this.marker]);
      // 在视角变化后更新飞机航向
      if (this.map && this.marker) {
        const refreshHeading = () => {
          const idx = Math.min(Math.max(0, this.currentIndex), this.points.length - 1);
          if (this.points[idx] && this.points[idx].Heading != null) {
            const heading = this.points[idx].Heading;
            this.applyMarkerHeading(this.marker, this.getMarkerHeading(heading));
          }
        };
        this.map.on('moveend', refreshHeading);
        this.map.on('rotate', refreshHeading);
        this.map.on('zoomchange', refreshHeading);
      }
      // 海拔显示标记
      if (this.altitudeMarker) { this.altitudeMarker.setMap(null); }
      this.altitudeMarker = new AMap.Marker({
        position: [path[0][0], path[0][1], this.points[0]['Altitude(m)']],
        content: `<div class="alt-label">${(this.points[0]['Altitude(m)'] || 0).toFixed(1)}m</div>`,
        offset: new AMap.Pixel(-40, -50),
        zIndex: 999
      });
      this.altitudeMarker.setMap(this.map);

      // 海拔点标记
      const step = Math.max(1, Math.floor(this.points.length / 30));
      this.altitudeLabels.forEach(label => {
        if (label && typeof label.setMap === 'function') {
          label.setMap(null);
        }
      });
      this.altitudeLabels = [];
      // for (let i = 0; i < this.points.length; i += step) {
      //   const p = this.points[i];
      //   const label = new AMap.Marker({
      //     position: [p.Longitude, p.Latitude],
      //     content: `<div class="alt-label">${(p['Altitude(m)'] || 0).toFixed(1)}m</div>`,
      //     offset: new AMap.Pixel(-20, -40),
      //     zIndex: 900
      //   });
      //   label.setMap(this.map);
      //   this.altitudeLabels.push(label);
      // }
    },
    getColorFromAltitude(ratio) {
      // 从蓝色（低海拔）到红色（高海拔）
      const r = Math.floor(255 * ratio);
      const g = Math.floor(255 * (1 - ratio));
      const b = Math.floor(255 * (1 - ratio));
      return `rgb(${r}, ${g}, ${b})`;
    },
    wgs84ToGcj02(lat, lon) {
      const pi = 3.14159265358979324;
      const a = 6378245.0;
      const ee = 0.00669342162296594323;

      const transformLat = (x, y) => {
        let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * pi) + 20.0 * Math.sin(2.0 * x * pi)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(y * pi) + 40.0 * Math.sin(y / 3.0 * pi)) * 2.0 / 3.0;
        ret += (160.0 * Math.sin(y / 12.0 * pi) + 320 * Math.sin(y * pi / 30.0)) * 2.0 / 3.0;
        return ret;
      };
      const transformLon = (x, y) => {
        let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * pi) + 20.0 * Math.sin(2.0 * x * pi)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(x * pi) + 40.0 * Math.sin(x / 3.0 * pi)) * 2.0 / 3.0;
        ret += (150.0 * Math.sin(x / 12.0 * pi) + 300.0 * Math.sin(x / 30.0 * pi)) * 2.0 / 3.0;
        return ret;
      };

      if (lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271) {
        return [lat, lon];
      }
      const dLat = transformLat(lon - 105.0, lat - 35.0);
      const dLon = transformLon(lon - 105.0, lat - 35.0);
      const radLat = lat / 180.0 * pi;
      let magic = Math.sin(radLat);
      magic = 1 - ee * magic * magic;
      const sqrtMagic = Math.sqrt(magic);
      const mgLat = lat + (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * pi);
      const mgLon = lon + (dLon * 180.0) / (a / sqrtMagic * Math.cos(radLat) * pi);
      return [mgLat, mgLon];
    },
    applyMarkerHeading(marker, heading) {
      if (!marker) return;
      if (typeof marker.setRotation === 'function') {
        marker.setRotation(heading);
      } else if (typeof marker.setAngle === 'function') {
        marker.setAngle(heading);
      } else if (typeof marker.setOptions === 'function') {
        marker.setOptions({ rotation: heading, angle: heading });
      }
    },
    getMarkerHeading(heading) {
      const mapRotation = (this.map && typeof this.map.getRotation === 'function') ? this.map.getRotation() : 0;
      // 当前展示角 = 航向 + 地图旋转偏移量
      return (heading + mapRotation + 360) % 360;
    },
    updatePosition(index) {
      if (!this.points[index] || !this.marker) return;
      const p = this.points[index];
      const pos = [p.Longitude, p.Latitude, p['Altitude(m)']];
      this.marker.setPosition(pos);
      const heading = p['Heading(deg)'] != null ? p['Heading(deg)'] : 0;
      const markerHeading = this.getMarkerHeading(heading);
      this.applyMarkerHeading(this.marker, markerHeading);
      this.map.setCenter(pos);
      if (this.altitudeMarker) {
        this.altitudeMarker.setPosition(pos);
        this.altitudeMarker.setContent(`<div class="alt-label">${(p['Altitude(m)'] || 0).toFixed(1)}m</div>`);
      }
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
    this.loadAMapScript().catch(err => {
      console.warn('AMap 预加载失败:', err);
    });
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

<style>
.alt-label {
  font-size: 12px;
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.5);
  white-space: nowrap;
}
</style>
