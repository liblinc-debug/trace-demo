<template>
  <div class="app-container" :class="themeMode">
    <div class="map-stage">
      <div class="map" ref="mapContainer"></div>
      <div class="floating-toolbar">

        <div class="controls">
          <select v-model="selectedDir" @change="onDirChange">
            <option value="" disabled>请选择日期目录...</option>
            <option v-for="d in dirs" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-model="selectedFile" @change="onFileChange">
            <option value="" disabled>请选择飞行记录...</option>
            <option v-for="f in files" :key="f" :value="f">{{ f }}</option>
          </select>
          <label class="control-label metric-select">
            <span>指标：</span>
            <select v-model="selectedMetric">
              <option v-for="option in metricOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <button @click="play" :disabled="!canPlay">播放</button>
          <button @click="pause" :disabled="!isPlaying">暂停</button>
          <label class="control-label">
            <span>变化点：</span>
            <input type="checkbox" v-model="showChangeMarkers" />
          </label>
          <label class="control-label">
            <span>风格：</span>
            <select v-model="themeMode">
              <option v-for="theme in themeOptions" :key="theme.value" :value="theme.value">{{ theme.label }}</option>
            </select>
          </label>
          <label class="control-label">
            <span>速度：</span>
            <select v-model.number="playbackRate">
              <option v-for="r in speedOptions" :key="r" :value="r">{{ r }}x</option>
            </select>
          </label>
          <input class="timeline-range" type="range" min="0" :max="points.length-1" v-model.number="currentIndex" @input="onSliderChange" />
        </div>
      </div>
      <div class="right-panel-group">
        <div class="panel realtime-info-panel" :class="themeMode" v-if="activePoint">
          <div class="panel-header">
            <div>实时信息</div>
            <button type="button" @click="realtimeInfoCollapsed = !realtimeInfoCollapsed">{{ realtimeInfoCollapsed ? '展开' : '收起' }}</button>
          </div>
          <div class="panel-body" v-show="!realtimeInfoCollapsed">
            <div class="info-grid">
              <div v-for="row in realtimeRows" :key="row.label" class="info-row">
                <span class="info-label">{{ row.label }}</span>
                <span class="info-value">{{ row.value }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="panel metric-info-panel" :class="themeMode" v-if="activePoint">
          <div class="panel-header">
            <div>{{ selectedMetric }} 说明</div>
            <button type="button" @click="metricInfoCollapsed = !metricInfoCollapsed">{{ metricInfoCollapsed ? '展开' : '收起' }}</button>
          </div>
          <div class="panel-body" v-show="!metricInfoCollapsed">
            <div class="metric-description" v-html="metricDescriptionHtml"></div>
          </div>
        </div>
      </div>
      <div class="chart-shell">
        <div class="chart" ref="chartContainer"></div>
      </div>
    </div>
  </div>
</template>

<script>
import axios from 'axios';
import Papa from 'papaparse';
import * as echarts from 'echarts';

export default {
  data() {
    return {
      dirs: [],
      files: [],
      selectedDir: '',
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
      legendValues: {},
      realtimeFields: [
        'Timestamp', 'Latitude', 'Longitude', 'Altitude(m)', 'Speed(m/s)', 'Climb(m/s)', 'Heading(deg)',
          'Loss_Rate(%)', 'Avg_Ping(ms)', 'Dist_to_Arm_Pt(m)', 'Flight_Dist(m)', 'WP_Speed(m/s)',
          'WP_Radius(m)', 'WP_Accel(m/s2)', 'Network', 'Band', 'Cell_ID', 'PCI', 'Signal_dBm', 'RSRP', 'RSRQ', 'SNR', 'RSSI', 'Jitter(ms)'
      ],
      themeMode: 'day',
      themeOptions: [
        { value: 'day', label: '白天' },
        { value: 'night', label: '黑夜' }
      ],
      selectedMetric: 'Signal_dBm',
      metricOptions: [
        { value: 'Signal_dBm', label: 'Signal_dBm' },
        { value: 'Avg_Ping(ms)', label: 'Avg_Ping(ms)' },
        { value: 'Loss_Rate(%)', label: 'Loss_Rate(%)' },
        { value: 'Jitter(ms)', label: 'Jitter(ms)' }
      ],
      metricInfoCollapsed: false,
      realtimeInfoCollapsed: false,
      showChangeMarkers: true,
      playbackRate: 1,
      speedOptions: [0.5, 1, 1.5, 2, 4, 8, 16],
      segmentLines: [],
      pointsConverted: false
    };
  },
  computed: {
    canPlay() {
      return this.points.length > 0 && !this.isPlaying;
    },
    activePoint() {
      return this.points[this.currentIndex] || null;
    },
    realtimeRows() {
      if (!this.activePoint) return [];
      return this.realtimeFields.map(field => ({
        label: field,
        value: this.formatRealtimeValue(field, this.activePoint[field])
      }));
    },
    metricDescriptionHtml() {
      const meta = {
        Signal_dBm: `
          <p><strong>Signal_dBm</strong> 信号强度评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≥ -85 dBm</font></span>：绿色表示信号很强，速率稳定，适用于无人机控制与高清视频回传。</li>
            <li><span class="normal"><font color="orange">一般 -95 ～ -86 dBm</font></span>：黄绿色表示信号较好，基本满足业务需求，边缘可能出现波动。</li>
            <li><span class="poor"><font color="yellow">较差 -105 ～ -96 dBm</font></span>：黄色表示信号较弱，可能影响速率和时延，需关注。</li>
            <li><span class="bad"><font color="red">很差 ≤ -106 dBm</font></span>：红色表示信号极弱，容易掉线或丢包，不适合高可靠应用。</li>
          </ul>`,
        'Avg_Ping(ms)': `
          <p><strong>Avg_Ping(ms)</strong> 时延评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≤ 30 ms</font></span>：绿色表示时延很低，适合远程控制、高清视频、实时图传。</li>
            <li><span class="normal"><font color="orange">一般 31 ～ 60 ms</font></span>：黄绿色表示满足普通业务，控制与图传基本可用。</li>
            <li><span class="poor"><font color="yellow">较差 61 ～ 100 ms</font></span>：黄色表示时延偏高，可能出现操控感下降或轻微卡顿。</li>
            <li><span class="bad"><font color="red">很差 > 100 ms</font></span>：红色表示时延较高，影响安全飞行和实时交互。</li>
          </ul>`,
        'Jitter(ms)': `
          <p><strong>Jitter(ms)</strong> 波动评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≤ 10 ms</font></span>：绿色表示时延非常稳定，控制指令流畅，视频无卡顿。</li>
            <li><span class="normal"><font color="orange">一般 11 ～ 20 ms</font></span>：黄绿色表示轻微波动，基本不影响业务。</li>
            <li><span class="poor"><font color="yellow">较差 21 ～ 50 ms</font></span>：黄色表示较明显抖动，可能影响操控体验或视频流畅度。</li>
            <li><span class="bad"><font color="red">很差 > 50 ms</font></span>：红色表示抖动严重，容易导致控制指令丢帧或视频花屏。</li>
          </ul>`,
        'Loss_Rate(%)': `
          <p><strong>Loss_Rate(%)</strong> 丢包率评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≤ 1%</font></span>：绿色表示链路稳定，数据传输可靠。</li>
            <li><span class="normal"><font color="orange">一般 1 ～ 3%</font></span>：黄绿色表示存在少量丢包，通常可接受。</li>
            <li><span class="poor"><font color="yellow">较差 3 ～ 8%</font></span>：黄色表示丢包显著，可能影响控制与图传。</li>
            <li><span class="bad"><font color="red">很差 > 8%</font></span>：红色表示丢包率高，需重点关注网络与链路质量。</li>
          </ul>`
      };
      return meta[this.selectedMetric] || '<p>请选择一个指标以查看对应说明。</p>';
    }
  },
  methods: {
    async fetchLogs() {
      const res = await axios.get('/api/logs');
      this.dirs = Array.isArray(res.data) ? res.data : [];
      if (this.dirs.length > 0) {
        this.selectedDir = this.dirs[0];
        await this.fetchFilesForDir();
      }
    },
    async fetchFilesForDir() {
      if (!this.selectedDir) {
        this.files = [];
        this.selectedFile = '';
        return;
      }
      const res = await axios.get('/api/logs', { params: { dir: this.selectedDir } });
      const files = Array.isArray(res.data) ? res.data : [];
      this.files = files.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
      if (this.files.length > 0) {
        this.selectedFile = this.files[0];
        await this.onFileChange();
      } else {
        this.selectedFile = '';
        this.points = [];
      }
    },
    async onDirChange() {
      await this.fetchFilesForDir();
    },
    async onFileChange() {
      this.pause();
      if (!this.selectedDir || !this.selectedFile) return;
      const res = await axios.get('/api/logs/file', {
        params: { dir: this.selectedDir, name: this.selectedFile }
      });
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
      this.pointsConverted = false;
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
      if (!this.pointsConverted) {
        const convertedPoints = this.points.map(p => {
          const [lat, lon] = this.wgs84ToGcj02(p.Latitude, p.Longitude);
          return {
            ...p,
            Latitude: lat,
            Longitude: lon
          };
        });
        this.points = convertedPoints;
        this.pointsConverted = true;
      }

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
        this.map.addControl(new AMap.ControlBar({ position: 'RB' }));
        this.map.addControl(new AMap.Scale());
      } else {
        const layers = this.map.getLayers ? this.map.getLayers() : [];
        const hasSat = layers.some(l => l instanceof AMap.TileLayer.Satellite);
        if (!hasSat) {
          this.map.setLayers([new AMap.TileLayer.Satellite()]);
        }
      }

      this.clearTrackLayers();

      const segments = [];
      for (let i = 0; i < this.points.length - 1; i += 1) {
        const p1 = this.points[i];
        const p2 = this.points[i + 1];
        segments.push({
          coordinates: [
            [p1.Longitude, p1.Latitude, p1['Altitude(m)']],
            [p2.Longitude, p2.Latitude, p2['Altitude(m)']]
          ],
          metric: this.getMetricValue(p1, this.selectedMetric)
        });
      }

      const hasLoca = window.AMap && window.Loca && typeof window.Loca.Container === 'function';
      if (hasLoca) {
        if (!this.locaContainer) {
          this.locaContainer = new Loca.Container({ map: this.map });
        }
        const source = new Loca.GeoJSONSource({
          data: {
            type: 'FeatureCollection',
            features: segments.map(seg => ({
              type: 'Feature',
              geometry: {
                type: 'LineString',
                coordinates: seg.coordinates
              },
              properties: {
                metric: seg.metric
              }
            }))
          }
        });
        this.locaLineLayer = new Loca.LineLayer({
          zIndex: 30,
          lineWidth: 3,
          opacity: 0.8
        });
        this.locaLineLayer.setSource(source, {
          height: (index, feature) => feature.geometry.coordinates[index][2],
          color: (index, feature) => this.getMetricColor(this.selectedMetric, feature.properties.metric)
        });
        this.locaContainer.add(this.locaLineLayer);
      } else {
        segments.forEach(seg => {
          const polyline = new AMap.Polyline({
            path: seg.coordinates,
            enableAltitude: true,
            strokeColor: this.getMetricColor(this.selectedMetric, seg.metric),
            strokeWeight: 4,
            showDir: false,
            geodesic: true,
            opacity: 0.9
          });
          polyline.setMap(this.map);
          this.segmentLines.push(polyline);
        });
      }

      if (this.altitudeLabels && this.altitudeLabels.length > 0) {
        this.altitudeLabels.forEach(label => label.setMap(null));
      }
      this.altitudeLabels = [];
      this.clearChangeMarkers();
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
        image: 'https://static.airsensor.top/static/img/icon/move_online.svg',
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

      this.renderChangeMarkers();
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
    normalizeMetric(value) {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric : null;
    },
    getMetricValue(point, ...keys) {
      for (const key of keys) {
        const value = point[key];
        if (value === null || value === undefined || value === '') continue;
        const numeric = this.normalizeMetric(value);
        if (numeric !== null) {
          return numeric;
        }
      }
      return null;
    },
    getMetricColor(metric, value) {
      if (value === null || value === undefined || Number.isNaN(value)) {
        return '#cbd5e1';
      }
      if (metric === 'Signal_dBm') {
        if (value >= -85) return '#22c55e';
        if (value >= -95) return '#84cc16';
        if (value >= -105) return '#eab308';
        return '#ef4444';
      }
      if (metric === 'Avg_Ping(ms)') {
        if (value <= 30) return '#22c55e';
        if (value <= 60) return '#84cc16';
        if (value <= 100) return '#eab308';
        return '#ef4444';
      }
      if (metric === 'Jitter(ms)') {
        if (value <= 10) return '#22c55e';
        if (value <= 20) return '#84cc16';
        if (value <= 50) return '#eab308';
        return '#ef4444';
      }
      if (metric === 'Loss_Rate(%)') {
        if (value <= 1) return '#22c55e';
        if (value <= 3) return '#84cc16';
        if (value <= 8) return '#eab308';
        return '#ef4444';
      }
      return '#cbd5e1';
    },
    clearTrackLayers() {
      if (this.segmentLines && this.segmentLines.length) {
        this.segmentLines.forEach(line => line.setMap(null));
        this.segmentLines = [];
      }
      if (this.locaLineLayer) {
        if (typeof this.locaLineLayer.setMap === 'function') {
          this.locaLineLayer.setMap(null);
        }
        if (typeof this.locaLineLayer.clear === 'function') {
          this.locaLineLayer.clear();
        }
        this.locaLineLayer = null;
      }
      if (this.locaContainer && typeof this.locaContainer.clear === 'function') {
        this.locaContainer.clear();
      }
      this.clearChangeMarkers();
    },
    clearChangeMarkers() {
      const removeMarkers = markers => {
        if (!Array.isArray(markers)) return [];
        markers.forEach(marker => {
          if (marker && typeof marker.setMap === 'function') {
            marker.setMap(null);
          }
        });
        return [];
      };
      this.cellIdMarkers = removeMarkers(this.cellIdMarkers);
      this.pciMarkers = removeMarkers(this.pciMarkers);
    },
    createChangeMarker(position, text, variant, compact = false) {
      if (!window.AMap || !position) return null;
      const marker = new AMap.Marker({
        position,
        content: compact
          ? `
          <div class="change-marker-dot-only">
            <span class="change-marker-dot"></span>
          </div>
        `
          : `
          <div class="change-marker ${variant}">
            <span class="change-marker-dot"></span>
            <span class="change-marker-text">${text}</span>
          </div>
        `,
        offset: new AMap.Pixel(-10, -10),
        zIndex: 1000
      });
      marker.setMap(this.map);
      return marker;
    },
    normalizeComparableValue(value) {
      if (value === null || value === undefined || value === '') return '';
      return String(value).trim();
    },
    getFieldChangePoints(fieldName) {
      const markers = [];
      for (let i = 1; i < this.points.length; i += 1) {
        const prevValue = this.points[i - 1]?.[fieldName];
        const currentValue = this.points[i]?.[fieldName];
        const prevNormalized = this.normalizeComparableValue(prevValue);
        const currentNormalized = this.normalizeComparableValue(currentValue);
        if (!prevNormalized || !currentNormalized || prevNormalized === currentNormalized) continue;
        markers.push({
          position: [this.points[i].Longitude, this.points[i].Latitude, this.points[i]['Altitude(m)']],
          value: currentValue
        });
      }
      return markers;
    },
    renderChangeMarkers() {
      this.clearChangeMarkers();
      if (!this.map || !this.points.length) return;

      const cellIdChanges = this.getFieldChangePoints('Cell_ID');
      const pciChanges = this.getFieldChangePoints('PCI');

      this.cellIdMarkers = cellIdChanges.map(change => this.createChangeMarker(
        change.position,
        `Cell_ID: ${change.value}`,
        'cell-id-marker',
        !this.showChangeMarkers
      )).filter(Boolean);

      this.pciMarkers = pciChanges.map(change => this.createChangeMarker(
        change.position,
        `PCI: ${change.value}`,
        'pci-marker',
        !this.showChangeMarkers
      )).filter(Boolean);
    },
    formatLegendValue(name, value) {
      if (value === null || value === undefined || Number.isNaN(value)) return '-';
      if (name === 'Loss Rate') return `${value.toFixed(1)}%`;
      if (name === 'Ping') return `${value.toFixed(1)}ms`;
      if (name === 'Dist') return `${value.toFixed(1)}m`;
      if (name === 'Altitude') return `${value.toFixed(1)}m`;
      if (name === 'Signal_dBm') return `${value.toFixed(1)}dBm`;
      if (name === 'Jitter(ms)') return `${value.toFixed(1)}ms`;
      return `${value}`;
    },
    formatRealtimeValue(field, value) {
      if (value === null || value === undefined || value === '') return '-';
      const numeric = Number(value);
      if (Number.isFinite(numeric)) {
        if (['Latitude', 'Longitude'].includes(field)) {
          return numeric.toFixed(6);
        }
        if (['Network', 'Band'].includes(field)) {
          return `${Math.round(numeric)}`;
        }
        return numeric.toFixed(1);
      }
      return String(value);
    },
    getThemeColors() {
      if (this.themeMode === 'night') {
        return {
          backgroundColor: '#020817',
          panelColor: 'rgba(2, 8, 23, 0.96)',
          dividerColor: 'rgba(148, 163, 184, 0.2)',
          textColor: '#f8fafc',
          axisColor: '#cbd5e1',
          gridColor: 'rgba(148, 163, 184, 0.2)',
          tooltipBg: 'rgba(3, 7, 18, 0.94)',
          tooltipBorder: 'rgba(148, 163, 184, 0.2)',
          lineLoss: '#fbbf24',
          linePing: '#22c55e',
          lineDist: '#38bdf8',
          lineAltitude: '#fb7185',
          lineSignal: '#a78bfa',
          lineJitter: '#fde68a'
        };
      }
      return {
        backgroundColor: '#ffffff',
        panelColor: '#ffffff',
        dividerColor: '#e5e7eb',
        textColor: '#1f2937',
        axisColor: '#4b5563',
        gridColor: '#e5e7eb',
        tooltipBg: '#ffffff',
        tooltipBorder: '#d1d5db',
        lineLoss: '#f59e0b',
        linePing: '#10b981',
        lineDist: '#0ea5e9',
        lineAltitude: '#f43f5e',
        lineSignal: '#8b5cf6',
        lineJitter: '#f59e0b'
      };
    },
    updatePosition(index) {
      const safeIndex = Number(index);
      if (!Number.isFinite(safeIndex)) return;
      this.currentIndex = safeIndex;
      if (!this.points[safeIndex] || !this.marker) return;
      const p = this.points[safeIndex];
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
      this.updateChartPointer(safeIndex);
    },
    handleChartClick(params) {
      if (!params || !this.points.length) return;
      const index = params.dataIndex;
      if (!Number.isFinite(index)) return;
      this.pause();
      this.updatePosition(index);
      this.chart.dispatchAction({
        type: 'showTip',
        seriesIndex: params.seriesIndex,
        dataIndex: index
      });
    },
    play() {
      if (this.isPlaying) return;
      this.isPlaying = true;
      const interval = Math.max(10, 200 / this.playbackRate);
      this.timer = setInterval(() => {
        if (this.currentIndex < this.points.length - 1) {
          this.currentIndex++;
          this.updatePosition(this.currentIndex);
        } else {
          this.pause();
        }
      }, interval);
    },
    pause() {
      this.isPlaying = false;
      clearInterval(this.timer);
      this.timer = null;
    },
    onSliderChange() {
      this.updatePosition(this.currentIndex);
    },
    buildChartOption() {
      const theme = this.getThemeColors();
      const series = [];
      const lossData = this.points.map(point => this.getMetricValue(point, 'Loss_Rate(%)', 'HB_Loss_Rate(%)'));
      const pingData = this.points.map(point => this.getMetricValue(point, 'Avg_Ping(ms)'));
      const distData = this.points.map(point => this.getMetricValue(point, 'Dist_to_Arm_Pt(m)'));
      const altitudeData = this.points.map(point => this.getMetricValue(point, 'Altitude(m)'));
      const signalData = this.points.map(point => this.getMetricValue(point, 'Signal_dBm'));
      const jitterData = this.points.map(point => this.getMetricValue(point, 'Jitter(ms)'));

      if (lossData.some(v => v !== null)) {
        series.push({
          name: 'Loss Rate',
          type: 'line',
          data: lossData,
          lineStyle: { color: theme.lineLoss },
          itemStyle: { color: theme.lineLoss }
        });
      }
      if (pingData.some(v => v !== null)) {
        series.push({
          name: 'Ping',
          type: 'line',
          data: pingData,
          lineStyle: { color: theme.linePing },
          itemStyle: { color: theme.linePing }
        });
      }
      if (distData.some(v => v !== null)) {
        series.push({
          name: 'Dist',
          type: 'line',
          data: distData,
          lineStyle: { color: theme.lineDist },
          itemStyle: { color: theme.lineDist }
        });
      }
      if (altitudeData.some(v => v !== null)) {
        series.push({
          name: 'Altitude',
          type: 'line',
          data: altitudeData,
          yAxisIndex: 1,
          lineStyle: { color: theme.lineAltitude },
          itemStyle: { color: theme.lineAltitude }
        });
      }
      if (signalData.some(v => v !== null)) {
        series.push({
          name: 'Signal_dBm',
          type: 'line',
          data: signalData,
          lineStyle: { color: theme.lineSignal },
          itemStyle: { color: theme.lineSignal }
        });
      }
      if (jitterData.some(v => v !== null)) {
        series.push({
          name: 'Jitter(ms)',
          type: 'line',
          data: jitterData,
          lineStyle: { color: theme.lineJitter },
          itemStyle: { color: theme.lineJitter }
        });
      }

      this.legendValues = {};
      series.forEach(item => {
        this.legendValues[item.name] = '-';
      });

      const visibleSeries = new Set(['Ping', 'Signal_dBm']);
      const selected = {};
      series.forEach(item => {
        const shouldShow = visibleSeries.has(item.name);
        if (!shouldShow && !series.some(seriesItem => visibleSeries.has(seriesItem.name))) {
          selected[item.name] = true;
        } else {
          selected[item.name] = shouldShow;
        }
      });

      return {
        backgroundColor: theme.backgroundColor,
        legend: {
          data: series.map(item => item.name),
          selected,
          top: 0,
          textStyle: { color: theme.textColor },
          formatter: name => `${name}: ${this.legendValues[name] || '-'}`
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: theme.tooltipBg,
          borderColor: theme.tooltipBorder,
          textStyle: { color: theme.textColor },
          formatter: params => {
            if (!params || params.length === 0) return '';
            const time = params[0].axisValue;
            let text = `<b>${time}</b><br/>`;
            params.forEach(param => {
              const value = param.value === null || param.value === undefined ? '-' : param.value;
              text += `${param.marker} ${param.seriesName}: ${value}<br/>`;
            });
            return text;
          }
        },
        xAxis: {
          type: 'category',
          data: this.points.map(point => point.Timestamp),
          axisLine: { lineStyle: { color: theme.axisColor } },
          axisLabel: { color: theme.axisColor },
          splitLine: { lineStyle: { color: theme.gridColor } }
        },
        yAxis: [
          {
            type: 'value',
            name: '% / ms / dBm',
            axisLine: { lineStyle: { color: theme.axisColor } },
            axisLabel: { color: theme.axisColor },
            splitLine: { lineStyle: { color: theme.gridColor } }
          },
          {
            type: 'value',
            name: 'Altitude (m)',
            position: 'right',
            axisLine: { lineStyle: { color: theme.axisColor } },
            axisLabel: { color: theme.axisColor },
            splitLine: { lineStyle: { color: theme.gridColor } }
          }
        ],
        series,
        axisPointer: {
          show: true,
          type: 'line',
          lineStyle: { color: theme.axisColor, width: 1 },
          snap: true
        }
      };
    },
    initChart() {
      this.$nextTick(() => {
        if (!this.chart) {
          this.chart = echarts.init(this.$refs.chartContainer);
        }
        this.chart.off('click', this.handleChartClick);
        this.chart.on('click', this.handleChartClick);
        this.chart.setOption(this.buildChartOption(), true);
      });
    },
    updateChartPointer(idx, seriesIndex = 0) {
      if (!this.chart) return;
      this.chart.dispatchAction({
        type: 'updateAxisPointer',
        xAxisIndex: 0,
        dataIndex: idx
      });
      this.chart.dispatchAction({
        type: 'showTip',
        seriesIndex,
        dataIndex: idx
      });
      const point = this.points[idx] || {};
      const legendUpdates = {
        'Loss Rate': this.getMetricValue(point, 'Loss_Rate(%)', 'HB_Loss_Rate(%)'),
        Ping: this.getMetricValue(point, 'Avg_Ping(ms)'),
        Dist: this.getMetricValue(point, 'Dist_to_Arm_Pt(m)'),
        Altitude: this.getMetricValue(point, 'Altitude(m)'),
        Signal_dBm: this.getMetricValue(point, 'Signal_dBm'),
        'Jitter(ms)': this.getMetricValue(point, 'Jitter(ms)')
      };
      Object.entries(legendUpdates).forEach(([name, value]) => {
        this.legendValues[name] = this.formatLegendValue(name, value);
      });
      this.chart.setOption({
        legend: {
          formatter: name => `${name}: ${this.legendValues[name] || '-'}`
        }
      });
    },
    handleWindowResize() {
      if (this.map && typeof this.map.resize === 'function') {
        this.map.resize();
      }
      if (this.chart && typeof this.chart.resize === 'function') {
        this.chart.resize();
      }
    }
  },
  watch: {
    themeMode() {
      this.initChart();
    },
    selectedMetric() {
      if (this.points.length > 0) {
        this.drawTrack();
      }
    },
    showChangeMarkers() {
      if (this.points.length > 0) {
        this.renderChangeMarkers();
      }
    }
  },
  mounted() {
    this.fetchLogs();
    this.loadAMapScript().catch(err => {
      console.warn('AMap 预加载失败:', err);
    });
    window.addEventListener('resize', this.handleWindowResize);
    window.addEventListener('beforeunload', () => {
      if (this.timer) clearInterval(this.timer);
    });
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleWindowResize);
  }
};
</script>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: #f5f5f5;
  color: #222;
  transition: background 0.25s ease, color 0.25s ease;
}
.app-container.day {
  background: #f5f5f5;
  color: #222;
}
.app-container.night {
  background: #020817;
  color: #f8fafc;
}
.controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 14px;
  transition: background 0.25s ease, border-color 0.25s ease;
}
.app-container.night .controls {
  background: rgba(2, 8, 23, 0.78);
}
.control-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.controls select,
.controls button,
.controls input[type="range"] {
  font-size: 1em;
}
.timeline-range {
  flex: 1 1 260px;
  min-width: 220px;
  width: 100%;
}
.floating-toolbar {
  position: absolute;
  top: 14px;
  left: 14px;
  right: 14px;
  z-index: 40;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}
.toolbar-title {
  align-self: flex-start;
  padding: 10px 16px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.08em;
  background: rgba(255, 255, 255, 0.72);
  color: #0f172a;
  backdrop-filter: blur(10px);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}
.app-container.night .toolbar-title {
  background: rgba(2, 8, 23, 0.72);
  color: #f8fafc;
}
.floating-toolbar .controls {
  width: 100%;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}
.app-container.night .controls select,
.app-container.night .controls button {
  background: rgba(8, 15, 33, 0.96);
  color: #f8fafc;
  border-color: rgba(148, 163, 184, 0.25);
}
.map-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  --side-panel-width: 360px;
}
.map {
  position: absolute;
  inset: 0;
  border: none;
}
.app-container.night .map {
  border-color: transparent;
}
.right-panel-group {
  position: absolute;
  top: 108px;
  right: 14px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(360px, calc(100% - 28px));
  max-height: calc(100% - 168px);
  overflow: hidden;
}
.panel {
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(8px);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}
.app-container.night .panel {
  background: rgba(2, 8, 23, 0.78);
  border-color: rgba(148, 163, 184, 0.2);
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  font-weight: 700;
  font-size: 13px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}
.panel-body {
  padding: 10px 12px;
  overflow: auto;
  max-height: 280px;
}
.metric-description p,
.metric-description ul {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: inherit;
}
.metric-description ul {
  padding-left: 18px;
}
.metric-description li {
  margin-bottom: 6px;
}
.metric-description .good { color: #16a34a; font-weight: 600; }
.metric-description .normal { color: #65a30d; font-weight: 600; }
.metric-description .poor { color: #ca8a04; font-weight: 600; }
.metric-description .bad { color: #dc2626; font-weight: 600; }
.info-grid {
  display: grid;
  grid-template-columns: minmax(72px, auto) 1fr;
  gap: 4px 10px;
  font-size: 11px;
  line-height: 1.3;
}
.panel-header button {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 12px;
}
.control-label.metric-select {
  min-width: 160px;
}
.control-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: #38bdf8;
}
.info-grid {
  display: grid;
  grid-template-columns: minmax(72px, auto) 1fr;
  gap: 4px 10px;
  font-size: 11px;
  line-height: 1.3;
}
.info-row {
  display: contents;
}
.info-label {
  font-weight: 700;
  opacity: 0.8;
}
.info-value {
  word-break: break-word;
}
.chart-shell {
  position: absolute;
  left: 14px;
  right: calc(14px + var(--side-panel-width) + 14px);
  bottom: 14px;
  z-index: 35;
  pointer-events: none;
}
.chart {
  height: clamp(210px, 22vh, 280px);
  width: 100%;
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
  transition: background 0.25s ease, border-color 0.25s ease;
  pointer-events: auto;
}
.app-container.night .chart {
  background: rgba(2, 8, 23, 0.82);
  border-color: rgba(148, 163, 184, 0.2);
}
@media (max-width: 1200px) {
  .map-stage {
    --side-panel-width: 320px;
  }
  .right-panel-group {
    top: 168px;
    width: min(320px, calc(100% - 28px));
  }
}
@media (max-width: 900px) {
  .map-stage {
    --side-panel-width: 0px;
  }
  .floating-toolbar {
    top: 10px;
    left: 10px;
    right: 10px;
  }
  .toolbar-title {
    font-size: 13px;
    padding: 8px 12px;
  }
  .right-panel-group {
    top: auto;
    bottom: 286px;
    right: 10px;
    left: 10px;
    width: auto;
    max-height: 34vh;
  }
  .chart-shell {
    left: 10px;
    right: 10px;
    bottom: 10px;
  }
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
.change-marker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.2);
}
.change-marker-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #38bdf8;
  /* box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.9); */
  flex: 0 0 auto;
}
.change-marker-text {
  line-height: 1;
}
.change-marker-dot-only {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: rgba(224, 242, 254, 0.96);
  border: 1px solid rgba(125, 211, 252, 0.8);
  /* box-shadow: 0 8px 20px rgba(15, 23, 42, 0.18); */
}
.change-marker.cell-id-marker {
  color: #7dd3fc;
  background: rgba(224, 242, 254, 0.96);
}
.change-marker.pci-marker {
  color: #1d4ed8;
  background: rgba(191, 219, 254, 0.96);
}
</style>
