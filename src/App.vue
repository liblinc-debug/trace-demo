<template>
  <div class="app-container" :class="themeMode">
    <div class="map-stage">
      <div class="map" ref="mapContainer"></div>
      <div class="panel-shell flight-log-panel-shell" v-if="aircraftOptions.length" :class="{ collapsed: flightLogCollapsed }">
        <button
          v-if="flightLogCollapsed"
          type="button"
          class="panel-collapse-handle flight-log-collapse-handle"
          @click="toggleFlightLogCollapsed(false)"
        >
          展开飞机列表
        </button>
        <div v-else class="panel flight-log-panel" :class="themeMode">
          <div class="panel-header">
            <div>飞机编号</div>
            <button type="button" @click="toggleFlightLogCollapsed(true)">收起</button>
          </div>
          <div class="panel-body flight-log-body">
            <div class="flight-log-tip">支持多选；第一架飞机用于趋势图和飞行动画，其余飞机叠加展示轨迹。</div>
            <select v-model="selectedAircraftIds" multiple :size="Math.max(8, Math.min(16, aircraftOptions.length || 8))">
              <option v-for="aircraft in aircraftOptions" :key="aircraft.aircraft_id" :value="aircraft.aircraft_id">
                {{ aircraft.aircraft_id }}（{{ aircraft.row_count }} 条）
              </option>
            </select>
          </div>
        </div>
      </div>
      <div class="floating-toolbar">

        <div class="controls">
          <label class="control-label time-control">
            <span>开始</span>
            <input v-model="startTime" type="datetime-local" step="1" />
          </label>
          <label class="control-label time-control">
            <span>结束</span>
            <input v-model="endTime" type="datetime-local" step="1" />
          </label>
          <button type="button" class="primary-button" @click="loadFlightData" :disabled="loading || !hasFlightSelection">
            {{ loading ? '查询中…' : '查询' }}
          </button>
          <button type="button" @click="downloadFlightData" :disabled="loading || !hasFlightSelection">
            下载
          </button>
          <label class="control-label metric-select">
            <span>指标</span>
            <select v-model="selectedMetric">
              <option v-for="option in metricOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <button @click="play" :disabled="!canPlay">播放</button>
          <button @click="pause" :disabled="!isPlaying">暂停</button>
          <label class="control-label">
            <span>速度</span>
            <select v-model.number="playbackRate">
              <option v-for="r in speedOptions" :key="r" :value="r">{{ r }}x</option>
            </select>
          </label>
          <label class="control-label">
            <span>站点名称</span>
            <input type="checkbox" v-model="showChangeMarkers" />
          </label>
          <label class="control-label">
            <span>风格</span>
            <select v-model="themeMode">
              <option v-for="theme in themeOptions" :key="theme.value" :value="theme.value">{{ theme.label }}</option>
            </select>
          </label>

          <input class="timeline-range" type="range" min="0" :max="points.length-1" v-model.number="currentIndex" @input="onSliderChange" />
          <span v-if="loadError" class="load-error" role="alert">{{ loadError }}</span>
        </div>
      </div>
      <div class="right-panel-group">
        <div class="panel-shell realtime-panel-shell" v-if="activePoint" :class="{ collapsed: realtimeInfoCollapsed }">
          <button
            v-if="realtimeInfoCollapsed"
            type="button"
            class="panel-collapse-handle"
            @click="toggleRealtimeInfoCollapsed(false)"
          >
            展开{{ activeRealtimeTabLabel }}
          </button>
          <div v-else class="panel realtime-info-panel" :class="themeMode">
            <div class="panel-header">
              <div class="panel-tabs">
                <button
                  type="button"
                  class="panel-tab"
                  :class="{ active: activeRealtimeTab === 'realtime' }"
                  @click="setRealtimeTab('realtime')"
                >
                  实时信息
                </button>
                <button
                  type="button"
                  class="panel-tab"
                  :class="{ active: activeRealtimeTab === 'stats' }"
                  @click="setRealtimeTab('stats')"
                >
                  统计信息
                </button>
              </div>
              <button type="button" @click="toggleRealtimeInfoCollapsed(true)">收起</button>
            </div>
            <div class="panel-body" v-if="activeRealtimeTab === 'realtime'">
              <div class="info-grid">
                <div v-for="row in realtimeRows" :key="row.label" class="info-row">
                  <span class="info-label">{{ row.label }}</span>
                  <span class="info-value">{{ row.value }}</span>
                </div>
              </div>
            </div>
            <div class="panel-body stats-body" v-else>
              <div class="info-grid stats-grid">
                <div v-for="row in flightStatsRows" :key="row.label" class="info-row">
                  <span class="info-label">{{ row.label }}</span>
                  <span class="info-value">{{ row.value }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="panel-shell metric-panel-shell" v-if="activePoint" :class="{ collapsed: metricInfoCollapsed }">
          <button
            v-if="metricInfoCollapsed"
            type="button"
            class="panel-collapse-handle"
            @click="toggleMetricInfoCollapsed(false)"
          >
            展开{{ selectedMetric }}说明
          </button>
          <div v-else class="panel metric-info-panel" :class="themeMode">
            <div class="panel-header">
              <div>{{ selectedMetric }} 说明</div>
              <button type="button" @click="toggleMetricInfoCollapsed(true)">收起</button>
            </div>
            <div class="panel-body">
              <div class="metric-description" v-html="metricDescriptionHtml"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="chart-shell" :class="{ collapsed: chartCollapsed }">
        <div v-show="!chartCollapsed" class="chart-panel">
          <div class="chart-panel-header">
            <span>趋势图</span>
            <button type="button" @click="toggleChartCollapsed">收起</button>
          </div>
          <div class="chart" ref="chartContainer"></div>
        </div>
        <button v-show="chartCollapsed" type="button" class="chart-collapse-handle" @click="toggleChartCollapsed">
          展开趋势图
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import axios from 'axios';
import * as echarts from 'echarts';

export default {
  data() {
    return {
      aircraftOptions: [],
      selectedAircraftIds: [],
      startTime: '',
      endTime: '',
      loading: false,
      loadError: '',
      points: [],
      flightTracks: [],
      currentIndex: 0,
      isPlaying: false,
      timer: null,
      map: null,
      marker: null,
      locaContainer: null,
      trackLayers: [],
      polylines: [],
      chart: null,
      mapScriptLoaded: false,
      altitudeMarker: null,
      altitudeLabels: [],
      legendValues: {},
      mapViewSyncHandler: null,
      siteMarkers: [],
      realtimeFields: [
        'Timestamp', 'Latitude', 'Longitude', 'Altitude(m)', 'Speed(m/s)', 'Climb(m/s)', 'Heading(deg)',
          'Loss_Rate(%)', 'Avg_Ping(ms)', 'Dist_to_Arm_Pt(m)', 'Flight_Dist(m)', 'WP_Speed(m/s)',
          'WP_Radius(m)', 'WP_Accel(m/s2)', 'Network', 'Band', 'Cell_ID', 'PCI', 'Signal_dBm', 'RSRP', 'RSRQ', 'SNR', 'RSSI', 'Jitter(ms)'
      ],
      themeMode: 'night',
      themeOptions: [
        { value: 'day', label: '白天' },
        { value: 'night', label: '黑夜' }
      ],
      activeRealtimeTab: 'realtime',
      selectedMetric: 'Signal_dBm',
      metricOptions: [
        { value: 'Signal_dBm', label: 'Signal_dBm' },
        { value: 'RSRQ', label: 'RSRQ_dB' },
        { value: 'SNR', label: 'SNR_dB' },
        { value: 'RSSI', label: 'RSSI_dBm' },
        { value: 'Avg_Ping(ms)', label: 'Avg_Ping(ms)' },
        { value: 'Loss_Rate(%)', label: 'Loss_Rate(%)' },
        { value: 'Jitter(ms)', label: 'Jitter(ms)' }
      ],
      metricInfoCollapsed: true,
      realtimeInfoCollapsed: true,
      showChangeMarkers: true,
      chartCollapsed: false,
      flightLogCollapsed: false,
      playbackRate: 1,
      speedOptions: [0.5, 1, 1.5, 2, 4, 8, 16],
      segmentLines: []
    };
  },
  computed: {
    canPlay() {
      return this.points.length > 0 && !this.isPlaying;
    },
    hasFlightSelection() {
      return this.selectedAircraftIds.length > 0 && Boolean(this.startTime) && Boolean(this.endTime);
    },
    activePoint() {
      return this.points[this.currentIndex] || null;
    },
    realtimeRows() {
      if (!this.activePoint) return [];
      return this.realtimeFields.map(field => ({
        label: field,
        value: this.formatRealtimeValue(field, this.getRealtimeFieldValue(this.activePoint, field))
      }));
    },
    flightStatsRows() {
      const points = this.points || [];
      if (!points.length) return [];
      const stats = this.getFlightStatistics(points);
      return [
        { label: '开始时间', value: stats.startTime },
        { label: '结束时间', value: stats.endTime },
        { label: '飞行时长', value: stats.duration },
        { label: '飞行里程', value: stats.flightDistance },
        { label: '平均速度', value: stats.averageSpeed },
        { label: '最大高度', value: stats.maxAltitude },
        { label: '最远距离', value: stats.maxDistance },
        { label: '数据总量', value: stats.totalCount },
        { label: '扇区(CELL)数量', value: `${stats.cellIdSiteCount} 个` },
        { label: '基站(PCI)数量', value: `${stats.pciSiteCount} 个` },
        { label: '扇区(CELL)切换', value: `${stats.cellIdSwitches} 次` },
        { label: '基站(PCI)切换', value: `${stats.pciSwitches} 次` }
        //,{ label: '总切换次数', value: `${stats.totalSwitches} 次` }
      ];
    },
    activeRealtimeTabLabel() {
      return this.activeRealtimeTab === 'stats' ? '统计信息' : '实时信息';
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
          </ul>`,
        RSRQ: `
          <p><strong>RSRQ</strong> 参考信号接收质量评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≥ -10 dB</font></span>：绿色表示信号质量很好，干扰极低。</li>
            <li><span class="normal"><font color="orange">一般 -12 ～ -11 dB</font></span>：黄绿色表示信号质量正常，可接受。</li>
            <li><span class="poor"><font color="yellow">较差 -15 ～ -13 dB</font></span>：黄色表示信号质量偏低，可能存在干扰。</li>
            <li><span class="bad"><font color="red">很差 ≤ -16 dB</font></span>：红色表示信号质量差，干扰严重。</li>
          </ul>
          <p>说明：5G 网络中 RSRQ 通常在 -3dB（极好）到 -20dB（极差）之间。</p>`,
        SNR: `
          <p><strong>SNR</strong> 信噪比评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≥ 20 dB</font></span>：绿色表示信噪比很好，数据传输稳定。</li>
            <li><span class="normal"><font color="orange">一般 13 ～ 19 dB</font></span>：黄绿色表示信噪比正常，满足业务需求。</li>
            <li><span class="poor"><font color="yellow">较差 5 ～ 12 dB</font></span>：黄色表示信噪比偏低，可能影响速率。</li>
            <li><span class="bad"><font color="red">很差 &lt; 5 dB</font></span>：红色表示信噪比差，易出现误码和重传。</li>
          </ul>`,
        RSSI: `
          <p><strong>RSSI</strong> 接收信号强度指示评估：</p>
          <ul>
            <li><span class="good"><font color="green">优良 ≥ -70 dBm</font></span>：绿色表示信号强度很强。</li>
            <li><span class="normal"><font color="orange">一般 -80 ～ -71 dBm</font></span>：黄绿色表示信号强度较好。</li>
            <li><span class="poor"><font color="yellow">较差 -90 ～ -81 dBm</font></span>：黄色表示信号强度偏弱。</li>
            <li><span class="bad"><font color="red">很差 ≤ -91 dBm</font></span>：红色表示信号强度很弱。</li>
          </ul>`
      };
      return meta[this.selectedMetric] || '<p>请选择一个指标以查看对应说明。</p>';
    }
  },
  methods: {
    async fetchAircrafts() {
      this.loading = true;
      this.loadError = '';
      try {
        const res = await axios.get('/api/flights/aircraft');
        this.aircraftOptions = Array.isArray(res.data) ? res.data : [];
        if (!this.aircraftOptions.length) {
          this.loadError = '数据库中暂无飞机记录';
          return;
        }
        const first = this.aircraftOptions[0];
        this.selectedAircraftIds = [first.aircraft_id];
        this.startTime = this.toDatetimeLocal(first.min_ts);
        this.endTime = this.toDatetimeLocal(Number(first.max_ts) + 1000);
        await this.loadFlightData();
      } catch (err) {
        console.error('飞机列表加载失败:', err);
        this.loadError = this.getRequestError(err, '飞机列表加载失败，请检查 ClickHouse 配置');
      } finally {
        this.loading = false;
      }
    },
    async loadFlightData() {
      this.pause();
      this.loadError = '';
      if (!this.hasFlightSelection) return;
      const start = new Date(this.startTime);
      const end = new Date(this.endTime);
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) {
        this.loadError = '结束时间必须晚于开始时间';
        return;
      }

      this.loading = true;
      try {
        const res = await axios.get('/api/flights', {
          params: {
            aircraftIds: [...new Set(this.selectedAircraftIds)].join(','),
            start: start.toISOString(),
            end: end.toISOString()
          }
        });
        const tracks = Array.isArray(res.data?.tracks) ? res.data.tracks : [];
        this.flightTracks = tracks
          .map(track => ({ name: track.name, points: this.normalizeTrackPoints(track.points) }))
          .filter(track => track.points.length > 0);
        this.points = this.flightTracks[0]?.points || [];
        this.currentIndex = 0;
        this.clearTrackLayers();
        if (this.points.length > 0) {
          await this.loadAMapScript();
          await this.drawTrack({ resetViewport: true });
        } else {
          this.clearFlightMarkers();
          this.loadError = '所选飞机和时段没有有效的轨迹数据';
        }
        this.initChart();
      } catch (err) {
        console.error('飞行数据加载失败:', err);
        this.clearFlightMarkers();
        this.loadError = this.getRequestError(err, '飞行数据加载失败，请稍后重试');
      } finally {
        this.loading = false;
      }
    },
    normalizeTrackPoints(points) {
      const validPoints = (Array.isArray(points) ? points : []).filter(p =>
        p.Latitude != null && p.Longitude != null &&
        p['Altitude(m)'] != null &&
        !isNaN(p.Latitude) && !isNaN(p.Longitude) && !isNaN(p['Altitude(m)']) &&
        p.Latitude >= -90 && p.Latitude <= 90 &&
        p.Longitude >= -180 && p.Longitude <= 180 &&
        p['Altitude(m)'] >= 0
      );
      return validPoints.map(p => {
        const [lat, lon] = this.wgs84ToGcj02(p.Latitude, p.Longitude);
        return {
          ...p,
          Latitude: lat,
          Longitude: lon
        };
      });
    },
    async downloadFlightData() {
      if (!this.hasFlightSelection) return;
      try {
        const res = await axios.get('/api/flights/export', {
          params: {
            aircraftIds: [...new Set(this.selectedAircraftIds)].join(','),
            start: new Date(this.startTime).toISOString(),
            end: new Date(this.endTime).toISOString()
          },
          responseType: 'blob'
        });
        const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `flight_${this.startTime.slice(0, 10)}_${this.endTime.slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
      } catch (err) {
        console.error('CSV 下载失败:', err);
        alert('CSV 下载失败，请缩短时间范围后重试');
      }
    },
    toDatetimeLocal(value) {
      const date = new Date(Number(value));
      if (Number.isNaN(date.getTime())) return '';
      const pad = number => String(number).padStart(2, '0');
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    },
    getRequestError(error, fallback) {
      return error?.response?.data?.error || fallback;
    },
    loadAMapScript() {
      if (this.mapScriptLoaded && window.AMap) {
        return Promise.resolve();
      }
      if (this.loadingMapScript) {
        return this.loadingMapScript;
      }
      this.loadingMapScript = new Promise((resolve, reject) => {
        const amapKey = import.meta.env.VITE_AMAP_KEY || '';
        const securityJsCode = import.meta.env.VITE_AMAP_SECURITY || '';
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
    getCurrentTrackPoint() {
      if (!this.points.length) return null;
      const safeIndex = Math.min(Math.max(0, Number(this.currentIndex) || 0), this.points.length - 1);
      return this.points[safeIndex] || this.points[0] || null;
    },
    getPointPosition(point) {
      if (!point) return null;
      return [point.Longitude, point.Latitude, point['Altitude(m)']];
    },
    getPointHeading(point) {
      if (!point) return 0;
      const heading = point['Heading(deg)'] != null ? point['Heading(deg)'] : point.Heading;
      return heading != null ? heading : 0;
    },
    applyMapViewState(viewState) {
      if (!this.map || !viewState) return;
      if (typeof viewState.zoom === 'number' && typeof this.map.setZoom === 'function') {
        this.map.setZoom(viewState.zoom);
      }
      if (viewState.center && typeof this.map.setCenter === 'function') {
        this.map.setCenter(viewState.center);
      }
      if (typeof viewState.rotation === 'number' && typeof this.map.setRotation === 'function') {
        this.map.setRotation(viewState.rotation);
      }
      if (typeof viewState.pitch === 'number' && typeof this.map.setPitch === 'function') {
        this.map.setPitch(viewState.pitch);
      }
    },
    getMapViewState() {
      if (!this.map) return null;
      const state = {};
      if (typeof this.map.getCenter === 'function') {
        state.center = this.map.getCenter();
      }
      if (typeof this.map.getZoom === 'function') {
        state.zoom = this.map.getZoom();
      }
      if (typeof this.map.getRotation === 'function') {
        state.rotation = this.map.getRotation();
      }
      if (typeof this.map.getPitch === 'function') {
        state.pitch = this.map.getPitch();
      }
      return state;
    },
    async drawTrack(options = {}) {
      if (this.points.length === 0) return;
      if (!this.mapScriptLoaded && !window.AMap) {
        await this.loadAMapScript();
      }
      if (typeof AMap === 'undefined') {
        console.error('AMap 未定义');
        return;
      }

      const activeTrack = this.flightTracks[0]?.points?.length ? this.flightTracks[0].points : this.points;
      this.points = activeTrack;
      const path = activeTrack.map(p => [p.Longitude, p.Latitude]);
      const currentPoint = this.getCurrentTrackPoint() || this.points[0];
      const currentPosition = this.getPointPosition(currentPoint) || path[0];
      const preserveViewport = !options.resetViewport;
      const viewState = preserveViewport ? this.getMapViewState() : null;
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

      const hasLoca = window.AMap && window.Loca && typeof window.Loca.Container === 'function';
      if (hasLoca) {
        if (!this.locaContainer) {
          this.locaContainer = new Loca.Container({ map: this.map });
        }
      }

      this.flightTracks.forEach(track => {
        const segments = [];
        for (let i = 0; i < track.points.length - 1; i += 1) {
          const p1 = track.points[i];
          const p2 = track.points[i + 1];
          segments.push({
            coordinates: [
              [p1.Longitude, p1.Latitude, p1['Altitude(m)']],
              [p2.Longitude, p2.Latitude, p2['Altitude(m)']]
            ],
            metric: this.getMetricValue(p1, this.selectedMetric)
          });
        }

        if (hasLoca) {
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
          const lineLayer = new Loca.LineLayer({
            zIndex: 30,
            lineWidth: 3,
            opacity: 0.8
          });
          lineLayer.setSource(source, {
            height: (index, feature) => feature.geometry.coordinates[index][2],
            color: (index, feature) => this.getMetricColor(this.selectedMetric, feature.properties.metric)
          });
          this.locaContainer.add(lineLayer);
          this.trackLayers.push(lineLayer);
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
            this.trackLayers.push(polyline);
          });
        }
      });

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

      const currentHeading = this.getPointHeading(currentPoint);
      const adjustedCurrentHeading = this.getMarkerHeading(currentHeading);
      if (!this.marker) {
        this.marker = new AMap.Marker({
          position: currentPosition,
          icon,
          offset: new AMap.Pixel(-16, -16)
        });
        this.marker.setMap(this.map);
      } else {
        this.marker.setPosition(currentPosition);
      }
      this.applyMarkerHeading(this.marker, adjustedCurrentHeading);
      if (!preserveViewport) {
        this.map.setCenter([path[0][0], path[0][1]]);
        this.map.setFitView([this.marker]);
      } else {
        this.applyMapViewState(viewState);
      }
      // 在视角变化后更新飞机航向
      if (this.map && this.marker) {
        if (this.mapViewSyncHandler) {
          this.map.off('moveend', this.mapViewSyncHandler);
          this.map.off('rotate', this.mapViewSyncHandler);
          this.map.off('zoomchange', this.mapViewSyncHandler);
        }
        this.mapViewSyncHandler = () => {
          const idx = Math.min(Math.max(0, this.currentIndex), this.points.length - 1);
          const heading = this.getPointHeading(this.points[idx]);
          this.applyMarkerHeading(this.marker, this.getMarkerHeading(heading));
        };
        this.map.on('moveend', this.mapViewSyncHandler);
        this.map.on('rotate', this.mapViewSyncHandler);
        this.map.on('zoomchange', this.mapViewSyncHandler);
      }
      // 海拔显示标记
      if (this.altitudeMarker) { this.altitudeMarker.setMap(null); }
      this.altitudeMarker = new AMap.Marker({
        position: currentPosition,
        content: `<div class="alt-label">${(currentPoint['Altitude(m)'] || 0).toFixed(1)}m</div>`,
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
      if (metric === 'RSRQ') {
        if (value >= -10) return '#22c55e';
        if (value >= -12) return '#84cc16';
        if (value >= -15) return '#eab308';
        return '#ef4444';
      }
      if (metric === 'SNR') {
        if (value >= 20) return '#22c55e';
        if (value >= 13) return '#84cc16';
        if (value >= 5) return '#eab308';
        return '#ef4444';
      }
      if (metric === 'RSSI') {
        if (value >= -70) return '#22c55e';
        if (value >= -80) return '#84cc16';
        if (value >= -90) return '#eab308';
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
      if (this.trackLayers && this.trackLayers.length) {
        this.trackLayers.forEach(layer => {
          if (!layer) return;
          if (typeof layer.setMap === 'function') {
            layer.setMap(null);
          }
          if (typeof layer.clear === 'function') {
            layer.clear();
          }
        });
        this.trackLayers = [];
      }
      if (this.segmentLines && this.segmentLines.length) {
        this.segmentLines.forEach(line => line.setMap(null));
        this.segmentLines = [];
      }
      if (this.locaContainer && typeof this.locaContainer.clear === 'function') {
        this.locaContainer.clear();
      }
      this.clearChangeMarkers();
    },
    clearFlightMarkers() {
      if (this.marker && typeof this.marker.setMap === 'function') {
        this.marker.setMap(null);
      }
      this.marker = null;
      if (this.altitudeMarker && typeof this.altitudeMarker.setMap === 'function') {
        this.altitudeMarker.setMap(null);
      }
      this.altitudeMarker = null;
      if (this.mapViewSyncHandler && this.map && typeof this.map.off === 'function') {
        this.map.off('moveend', this.mapViewSyncHandler);
        this.map.off('rotate', this.mapViewSyncHandler);
        this.map.off('zoomchange', this.mapViewSyncHandler);
      }
      this.mapViewSyncHandler = null;
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
      this.siteMarkers = removeMarkers(this.siteMarkers);
    },
    createChangeMarker(position, text, variant, compact = false, offset = [0, 0]) {
      if (!window.AMap || !position) return null;
      const marker = new AMap.Marker({
        position,
        content: compact
          ? `
          <div class="change-marker-dot-only ${variant}">
            <span class="change-marker-dot"></span>
          </div>
        `
          : `
          <div class="change-marker ${variant}">
            <span class="change-marker-dot"></span>
            <span class="change-marker-text">${text}</span>
          </div>
        `,
        offset: new AMap.Pixel(offset[0], offset[1]),
        zIndex: 1000
      });
      marker.setMap(this.map);
      return marker;
    },
    normalizeComparableValue(value) {
      if (value === null || value === undefined || value === '') return '';
      return String(value).trim();
    },
    getFieldChangePoints(points, fieldName) {
      const trackPoints = Array.isArray(points) ? points : this.points;
      const markers = [];
      for (let i = 1; i < trackPoints.length; i += 1) {
        const prevValue = this.getRealtimeFieldValue(trackPoints[i - 1], fieldName);
        const currentValue = this.getRealtimeFieldValue(trackPoints[i], fieldName);
        const prevNormalized = this.normalizeComparableValue(prevValue);
        const currentNormalized = this.normalizeComparableValue(currentValue);
        if (!prevNormalized || !currentNormalized || prevNormalized === currentNormalized) continue;
        markers.push({
          position: [trackPoints[i].Longitude, trackPoints[i].Latitude, trackPoints[i]['Altitude(m)']],
          value: currentValue
        });
      }
      return markers;
    },
    renderChangeMarkers() {
      this.clearChangeMarkers();
      if (!this.map || !this.flightTracks.length) return;

      const markers = [];
      this.flightTracks.forEach(track => {
        const points = Array.isArray(track.points) ? track.points : [];
        if (points.length < 2) return;

        const cellIdChanges = this.getFieldChangePoints(points, 'Cell_ID');
        const pciChanges = this.getFieldChangePoints(points, 'PCI');
        cellIdChanges.forEach(change => {
          markers.push(this.createChangeMarker(
            change.position,
            `Cell_ID: ${this.formatCodeValue(change.value)}`,
            'cell-id-marker',
            !this.showChangeMarkers,
            [0, -9]
          ));
        });

        pciChanges.forEach(change => {
          markers.push(this.createChangeMarker(
            change.position,
            `PCI: ${this.formatCodeValue(change.value)}`,
            'pci-marker',
            !this.showChangeMarkers,
            [0, 8]
          ));
        });
      });

      this.siteMarkers = markers.filter(Boolean);
    },
    formatLegendValue(name, value) {
      if (value === null || value === undefined || Number.isNaN(value)) return '-';
      if (name === 'Loss Rate') return `${value.toFixed(1)}%`;
      if (name === 'Ping') return `${value.toFixed(1)}ms`;
      if (name === 'Speed(m/s)') return `${value.toFixed(1)}m/s`;
      if (name === 'Dist') return `${value.toFixed(1)}m`;
      if (name === 'Altitude') return `${value.toFixed(1)}m`;
      if (name === 'Signal_dBm') return `${value.toFixed(1)}dBm`;
      if (name === 'Jitter(ms)') return `${value.toFixed(1)}ms`;
      return `${value}`;
    },
    formatRealtimeValue(field, value) {
      if (value === null || value === undefined || value === '') return '-';
      if (field === 'Cell_ID' || field === 'PCI') {
        return this.formatCodeValue(value);
      }
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
    getRealtimeFieldValue(point, field) {
      const aliases = {
        Timestamp: ['timestamp', 'Time', 'time'],
        Latitude: ['lat', 'Lat'],
        Longitude: ['lon', 'Lng', 'lng', 'Lon'],
        'Altitude(m)': ['Altitude', 'altitude', 'Altitude_m'],
        'Speed(m/s)': ['Speed', 'speed'],
        'Climb(m/s)': ['Climb', 'climb'],
        'Heading(deg)': ['Heading', 'heading'],
        'Loss_Rate(%)': ['LossRate', 'HB_Loss_Rate(%)'],
        'Avg_Ping(ms)': ['Avg_Ping', 'Ping', 'avg_ping'],
        'Dist_to_Arm_Pt(m)': ['Dist', 'Distance_to_Arm_Pt(m)'],
        'Flight_Dist(m)': ['FlightDist', 'Flight_Distance(m)'],
        'WP_Speed(m/s)': ['WP_Speed'],
        'WP_Radius(m)': ['WP_Radius'],
        'WP_Accel(m/s2)': ['WP_Accel'],
        Network: ['network'],
        Band: ['band'],
        Cell_ID: ['CellID', 'cell_id', 'cellId', 'cellid'],
        PCI: ['pci', 'Pci'],
        Signal_dBm: ['Signal', 'signal_dBm'],
        RSRP: ['rsrp'],
        RSRQ: ['rsrq'],
        SNR: ['snr'],
        RSSI: ['rssi'],
        'Jitter(ms)': ['Jitter', 'jitter']
      };
      return this.getFieldWithAliases(point, field, aliases[field] || []);
    },
    getFieldWithAliases(point, field, extraAliases = []) {
      if (!point) return null;
      const keys = [field, ...extraAliases];
      for (const key of keys) {
        if (!Object.prototype.hasOwnProperty.call(point, key)) continue;
        const value = point[key];
        if (value !== null && value !== undefined && value !== '') {
          return value;
        }
      }
      return null;
    },
    formatCodeValue(value) {
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'number' && Number.isFinite(value)) {
        return `${Math.trunc(value)}`;
      }
      return String(value).trim();
    },
    formatTimestampDisplay(value) {
      if (value === null || value === undefined || value === '') return '-';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      const pad = num => `${num}`.padStart(2, '0');
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    },
    formatDuration(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) return '-';
      const total = Math.round(seconds);
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const secs = total % 60;
      const parts = [];
      if (hours > 0) parts.push(`${hours} 小时`);
      if (minutes > 0 || hours > 0) parts.push(`${minutes} 分`);
      parts.push(`${secs} 秒`);
      return parts.join(' ');
    },
    formatMeters(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return '-';
      return `${numeric.toFixed(1)} m`;
    },
    getTimestampMs(point) {
      if (!point) return null;
      const value = this.getRealtimeFieldValue(point, 'Timestamp');
      if (value === null || value === undefined || value === '') return null;
      const date = new Date(value);
      if (!Number.isNaN(date.getTime())) {
        return date.getTime();
      }
      const numeric = Number(value);
      if (Number.isFinite(numeric)) {
        return numeric;
      }
      return null;
    },
    getPointCoordinates(point) {
      if (!point) return null;
      const lat = Number(this.getRealtimeFieldValue(point, 'Latitude'));
      const lon = Number(this.getRealtimeFieldValue(point, 'Longitude'));
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
      return { lat, lon };
    },
    getGroundDistanceMeters(pointA, pointB) {
      const a = this.getPointCoordinates(pointA);
      const b = this.getPointCoordinates(pointB);
      if (!a || !b) return null;
      const toRad = deg => (deg * Math.PI) / 180;
      const earthRadius = 6371000;
      const dLat = toRad(b.lat - a.lat);
      const dLon = toRad(b.lon - a.lon);
      const lat1 = toRad(a.lat);
      const lat2 = toRad(b.lat);
      const sinLat = Math.sin(dLat / 2);
      const sinLon = Math.sin(dLon / 2);
      const h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;
      return 2 * earthRadius * Math.asin(Math.min(1, Math.sqrt(h)));
    },
    getFlightStatistics(points) {
      const validPoints = Array.isArray(points) ? points.filter(Boolean) : [];
      if (!validPoints.length) {
        return {
          startTime: '-',
          endTime: '-',
          duration: '-',
          flightDistance: '-',
          averageSpeed: '-',
          maxAltitude: '-',
          maxDistance: '-',
          totalCount: '0 条',
          cellIdSiteCount: 0,
          pciSiteCount: 0,
          cellIdSwitches: 0,
          pciSwitches: 0,
          totalSwitches: 0
        };
      }

      const startTimestampMs = this.getTimestampMs(validPoints[0]);
      const endTimestampMs = this.getTimestampMs(validPoints[validPoints.length - 1]);
      const altitudeValues = validPoints
        .map(point => Number(this.getRealtimeFieldValue(point, 'Altitude(m)')))
        .filter(value => Number.isFinite(value));
      const speedValues = validPoints
        .map(point => Number(this.getRealtimeFieldValue(point, 'Speed(m/s)')))
        .filter(value => Number.isFinite(value));
      let flightDistance = 0;
      let farthestDistance = 0;
      const takeoffPoint = validPoints[0];
      for (let i = 1; i < validPoints.length; i += 1) {
        const segmentDistance = this.getGroundDistanceMeters(validPoints[i - 1], validPoints[i]);
        if (Number.isFinite(segmentDistance)) {
          flightDistance += segmentDistance;
        }
      }
      validPoints.forEach(point => {
        const dist = this.getGroundDistanceMeters(takeoffPoint, point);
        if (Number.isFinite(dist) && dist > farthestDistance) {
          farthestDistance = dist;
        }
      });

      let cellIdSwitches = 0;
      let pciSwitches = 0;
      const cellIdSites = new Set();
      const pciSites = new Set();
      let prevCell = this.normalizeComparableValue(this.getRealtimeFieldValue(validPoints[0], 'Cell_ID'));
      let prevPci = this.normalizeComparableValue(this.getRealtimeFieldValue(validPoints[0], 'PCI'));
      if (prevCell) cellIdSites.add(prevCell);
      if (prevPci) pciSites.add(prevPci);
      for (let i = 1; i < validPoints.length; i += 1) {
        const currentCell = this.normalizeComparableValue(this.getRealtimeFieldValue(validPoints[i], 'Cell_ID'));
        const currentPci = this.normalizeComparableValue(this.getRealtimeFieldValue(validPoints[i], 'PCI'));
        if (currentCell) cellIdSites.add(currentCell);
        if (currentPci) pciSites.add(currentPci);
        if (prevCell && currentCell && prevCell !== currentCell) {
          cellIdSwitches += 1;
        }
        if (prevPci && currentPci && prevPci !== currentPci) {
          pciSwitches += 1;
        }
        if (currentCell) prevCell = currentCell;
        if (currentPci) prevPci = currentPci;
      }

      return {
        startTime: this.formatTimestampDisplay(validPoints[0] ? this.getRealtimeFieldValue(validPoints[0], 'Timestamp') : null),
        endTime: this.formatTimestampDisplay(validPoints[validPoints.length - 1] ? this.getRealtimeFieldValue(validPoints[validPoints.length - 1], 'Timestamp') : null),
        duration: startTimestampMs !== null && endTimestampMs !== null
          ? this.formatDuration(Math.max(0, (endTimestampMs - startTimestampMs) / 1000))
          : '-',
        flightDistance: this.formatMeters(flightDistance),
        averageSpeed: speedValues.length ? `${(speedValues.reduce((sum, value) => sum + value, 0) / speedValues.length).toFixed(1)} m/s` : '-',
        maxAltitude: this.formatMeters(altitudeValues.length ? Math.max(...altitudeValues) : null),
        maxDistance: this.formatMeters(farthestDistance),
        totalCount: `${validPoints.length} 条`,
        cellIdSiteCount: cellIdSites.size,
        pciSiteCount: pciSites.size,
        cellIdSwitches,
        pciSwitches,
        totalSwitches: cellIdSwitches + pciSwitches
      };
    },
    getThemeColors() {
      if (this.themeMode === 'night') {
        return {
          backgroundColor: '#0e1a2b',
          panelColor: 'rgba(14, 26, 43, 0.96)',
          dividerColor: '#1d3050',
          textColor: '#dce8f7',
          axisColor: '#8aa2c0',
          gridColor: 'rgba(93, 116, 149, 0.22)',
          tooltipBg: 'rgba(16, 31, 51, 0.98)',
          tooltipBorder: '#1d3050',
          lineLoss: '#fbbf24',
          linePing: '#4ade80',
          lineSpeed: '#37d5f2',
          lineDist: '#60a5fa',
          lineAltitude: '#f87171',
          lineSignal: '#a78bfa',
          lineJitter: '#fb923c'
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
        lineSpeed: '#0891b2',
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
      const heading = this.getPointHeading(p);
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
      const speedData = this.points.map(point => this.getMetricValue(point, 'Speed(m/s)', 'Speed'));
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
      if (speedData.some(v => v !== null)) {
        series.push({
          name: 'Speed(m/s)',
          type: 'line',
          data: speedData,
          lineStyle: { color: theme.lineSpeed },
          itemStyle: { color: theme.lineSpeed }
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

      const visibleSeries = new Set(['Ping']);
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
          data: this.points.map(point => this.getRealtimeFieldValue(point, 'Timestamp')),
          axisLine: { lineStyle: { color: theme.axisColor } },
          axisLabel: { color: theme.axisColor },
          splitLine: { lineStyle: { color: theme.gridColor } }
        },
        yAxis: [
          {
            type: 'value',
            name: '% / ms / dBm / m/s',
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
        'Speed(m/s)': this.getMetricValue(point, 'Speed(m/s)', 'Speed'),
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
      if (this.chart && typeof this.chart.resize === 'function' && !this.chartCollapsed) {
        this.chart.resize();
      }
    },
    toggleChartCollapsed() {
      this.chartCollapsed = !this.chartCollapsed;
      if (!this.chartCollapsed) {
        this.$nextTick(() => {
          if (this.chart && typeof this.chart.resize === 'function') {
            this.chart.resize();
          }
        });
      }
    },
    toggleRealtimeInfoCollapsed(nextState) {
      this.realtimeInfoCollapsed = nextState;
    },
    setRealtimeTab(tab) {
      this.activeRealtimeTab = tab;
    },
    toggleMetricInfoCollapsed(nextState) {
      this.metricInfoCollapsed = nextState;
    },
    toggleFlightLogCollapsed(nextState) {
      this.flightLogCollapsed = nextState;
    }
  },
  watch: {
    themeMode() {
      this.initChart();
    },
    selectedMetric() {
      if (this.flightTracks.length > 0) {
        this.drawTrack({ resetViewport: false });
      }
    },
    showChangeMarkers() {
      if (this.points.length > 0) {
        this.renderChangeMarkers();
      }
    },
    chartCollapsed() {
      this.$nextTick(() => {
        if (this.chart && typeof this.chart.resize === 'function' && !this.chartCollapsed) {
          this.chart.resize();
        }
      });
    }
  },
  mounted() {
    this.fetchAircrafts();
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
    if (this.map && this.mapViewSyncHandler) {
      this.map.off('moveend', this.mapViewSyncHandler);
      this.map.off('rotate', this.mapViewSyncHandler);
      this.map.off('zoomchange', this.mapViewSyncHandler);
    }
  }
};
</script>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100dvh;
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
.controls input[type="datetime-local"],
.controls input[type="range"] {
  font-size: 1em;
}
.download-button {
  padding: 8px 14px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.16);
  color: inherit;
  cursor: pointer;
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
  /* width: 100%; */
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}
.app-container.night .controls select,
.app-container.night .controls button,
.app-container.night .controls input[type="datetime-local"] {
  background: rgba(8, 15, 33, 0.96);
  color: #f8fafc;
  border-color: rgba(148, 163, 184, 0.25);
}
.app-container.night .download-button {
  background: rgba(8, 15, 33, 0.96);
  color: #f8fafc;
  border-color: rgba(148, 163, 184, 0.25);
}
.flight-log-panel-shell {
  position: absolute;
  top: 108px;
  left: 14px;
  z-index: 36;
  display: flex;
  justify-content: flex-start;
  pointer-events: none;
}
.flight-log-panel-shell.collapsed {
  width: 56px;
}
.flight-log-panel-shell .flight-log-panel {
  width: min(290px, calc(100vw - 28px));
}
.flight-log-panel-shell .flight-log-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.flight-log-tip {
  font-size: 12px;
  line-height: 1.4;
  color: inherit;
  opacity: 0.82;
}
.flight-log-panel-shell select[multiple] {
  width: 100%;
  min-height: 240px;
  max-height: 40vh;
  padding: 8px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.96);
  color: inherit;
}
.app-container.night .flight-log-panel-shell select[multiple] {
  background: rgba(8, 15, 33, 0.96);
  border-color: rgba(148, 163, 184, 0.25);
}
.flight-log-panel-shell select[multiple] option {
  padding: 6px 8px;
}
.map-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
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
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  width: fit-content;
  max-height: calc(100% - 168px);
  overflow: hidden;
  pointer-events: none;
}
.panel-shell {
  width: fit-content;
  max-width: min(360px, calc(100vw - 28px));
  display: flex;
  justify-content: flex-end;
  pointer-events: auto;
}
.flight-log-panel-shell.panel-shell {
  max-width: min(290px, calc(100vw - 28px));
}
.panel-shell.collapsed {
  width: 56px;
}
.realtime-panel-shell .panel,
.metric-panel-shell .panel {
  width: min(360px, calc(100vw - 28px));
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
  pointer-events: auto;
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
.panel-tabs {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.panel-tab {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: inherit;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.panel-tab.active {
  background: rgba(56, 189, 248, 0.18);
  border-color: rgba(56, 189, 248, 0.38);
  color: #0284c7;
}
.app-container.night .panel-tab {
  background: rgba(15, 23, 42, 0.65);
  border-color: rgba(148, 163, 184, 0.25);
}
.app-container.night .panel-tab.active {
  background: rgba(14, 165, 233, 0.2);
  color: #7dd3fc;
}
.panel-body {
  padding: 10px 12px;
  overflow: auto;
  max-height: 280px;
}
.stats-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
.panel-collapse-handle {
  width: 56px;
  height: clamp(160px, 18vh, 220px);
  display: flex;
  align-items: center;
  justify-content: center;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  letter-spacing: 0.12em;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
  color: inherit;
  cursor: pointer;
  font-size: 12px;
  pointer-events: auto;
}
.app-container.night .panel-collapse-handle {
  background: rgba(2, 8, 23, 0.82);
  border-color: rgba(148, 163, 184, 0.2);
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
.switch-summary {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px dashed rgba(56, 189, 248, 0.28);
  white-space: pre-line;
  font-size: 12px;
  line-height: 1.6;
}
.app-container.night .switch-summary {
  background: rgba(8, 47, 73, 0.4);
  border-color: rgba(125, 211, 252, 0.24);
}
.chart-shell {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 14px;
  z-index: 35;
  pointer-events: none;
}
.chart-shell.collapsed {
  left: 14px;
  right: auto;
  width: 56px;
}
.chart-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  pointer-events: auto;
}
.chart-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 18px 18px 0 0;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-bottom: none;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(12px);
}
.app-container.night .chart-panel-header {
  background: rgba(2, 8, 23, 0.82);
}
.chart-panel-header span {
  font-size: 13px;
  font-weight: 700;
  color: inherit;
}
.chart-panel-header button,
.chart-collapse-handle {
  border: none;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.16);
  color: inherit;
  cursor: pointer;
  font-size: 12px;
  padding: 6px 12px;
}
.chart-collapse-handle {
  width: 56px;
  height: clamp(210px, 22vh, 280px);
  display: flex;
  align-items: center;
  justify-content: center;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  letter-spacing: 0.12em;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 20px;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}
.app-container.night .chart-collapse-handle {
  background: rgba(2, 8, 23, 0.82);
}
.chart {
  height: clamp(210px, 22vh, 280px);
  width: 100%;
  border-radius: 0 0 20px 20px;
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
  .flight-log-panel-shell {
    top: 168px;
  }
  .right-panel-group {
    top: 168px;
    width: fit-content;
  }
  .panel-shell {
    max-width: min(320px, calc(100vw - 28px));
  }
  .realtime-panel-shell .panel,
  .metric-panel-shell .panel {
    width: min(320px, calc(100vw - 28px));
  }
}
@media (max-width: 900px) {
  .floating-toolbar {
    top: 10px;
    left: 10px;
    right: 10px;
  }
  .flight-log-panel-shell {
    top: 150px;
    left: 10px;
  }
  .toolbar-title {
    font-size: 13px;
    padding: 8px 12px;
  }
  .right-panel-group {
    top: auto;
    bottom: 286px;
    right: 0;
    left: auto;
    width: fit-content;
    max-height: 34vh;
  }
  .panel-shell {
    max-width: min(320px, calc(100vw - 20px));
  }
  .panel-shell.collapsed {
    width: 50px;
  }
  .realtime-panel-shell .panel,
  .metric-panel-shell .panel {
    width: min(320px, calc(100vw - 20px));
  }
  .panel-collapse-handle {
    width: 50px;
    height: clamp(120px, 16vh, 180px);
  }
  .chart-shell {
    left: 10px;
    right: 10px;
    bottom: 10px;
  }
  .chart-shell.collapsed {
    left: 10px;
    right: auto;
    width: 50px;
  }
  .chart-collapse-handle {
    width: 50px;
  }
}

/* 与无人机平台门户统一的地面站视觉主题 */
.app-container {
  --portal-bg: #070d16;
  --portal-panel: rgba(14, 26, 43, 0.94);
  --portal-panel-strong: rgba(7, 13, 22, 0.92);
  --portal-panel-soft: rgba(16, 31, 51, 0.92);
  --portal-line: #1d3050;
  --portal-text: #dce8f7;
  --portal-text-dim: #8aa2c0;
  --portal-text-faint: #5d7495;
  --portal-accent: #37d5f2;
  --portal-accent-soft: rgba(55, 213, 242, 0.14);
  --portal-shadow: 0 18px 48px rgba(0, 0, 0, 0.36);
  background: var(--portal-bg);
  color: var(--portal-text);
  font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.app-container.day {
  --portal-bg: #eaf2f9;
  --portal-panel: rgba(250, 253, 255, 0.94);
  --portal-panel-strong: rgba(241, 247, 252, 0.94);
  --portal-panel-soft: rgba(229, 240, 248, 0.94);
  --portal-line: rgba(45, 78, 112, 0.22);
  --portal-text: #13243a;
  --portal-text-dim: #526b86;
  --portal-text-faint: #7690aa;
  --portal-accent: #087f9f;
  --portal-accent-soft: rgba(8, 127, 159, 0.12);
  --portal-shadow: 0 18px 44px rgba(35, 65, 92, 0.2);
  background: var(--portal-bg);
  color: var(--portal-text);
}

.map-stage {
  background: var(--portal-bg);
}

.map-stage::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  box-shadow: inset 0 0 96px rgba(7, 13, 22, 0.2);
}

.floating-toolbar {
  top: 14px;
  left: 14px;
  right: 14px;
}

.floating-toolbar .controls {
  position: relative;
  gap: 8px;
  padding: 10px 12px;
  overflow: hidden;
  border: 1px solid var(--portal-line);
  border-radius: 16px;
  background: var(--portal-panel-strong);
  box-shadow: var(--portal-shadow);
  backdrop-filter: blur(16px) saturate(125%);
}

.floating-toolbar .controls::before,
.panel::before {
  content: "";
  position: absolute;
  top: 0;
  left: 14px;
  right: 14px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--portal-accent), transparent);
  opacity: 0.8;
  pointer-events: none;
}

.control-label {
  color: var(--portal-text-dim);
  font-size: 12px;
  white-space: nowrap;
}

.controls select,
.controls button,
.controls input[type="datetime-local"] {
  height: 34px;
  padding: 0 11px;
  border: 1px solid var(--portal-line);
  border-radius: 9px;
  outline: 0;
  background: var(--portal-panel-soft);
  color: var(--portal-text);
  font: inherit;
  font-size: 13px;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.controls button {
  cursor: pointer;
}

.controls input[type="datetime-local"] {
  min-width: 184px;
}

.controls .primary-button {
  border-color: var(--portal-accent);
  background: var(--portal-accent-soft);
  color: var(--portal-accent);
  font-weight: 700;
}

.load-error {
  flex: 1 1 100%;
  color: #f87171;
  font-size: 12px;
  line-height: 1.4;
}

.controls button:hover:not(:disabled),
.controls select:hover {
  border-color: var(--portal-accent);
  background: var(--portal-accent-soft);
  color: var(--portal-accent);
}

.controls button:active:not(:disabled) {
  transform: translateY(1px);
}

.controls button:disabled {
  color: var(--portal-text-faint);
  cursor: not-allowed;
  opacity: 0.5;
}

.controls button:focus-visible,
.controls select:focus-visible,
.controls input[type="datetime-local"]:focus-visible,
.panel button:focus-visible,
.panel-collapse-handle:focus-visible,
.chart-collapse-handle:focus-visible {
  outline: 2px solid var(--portal-accent);
  outline-offset: 2px;
}

.control-label input[type="checkbox"] {
  accent-color: var(--portal-accent);
}

.timeline-range {
  height: 4px;
  margin: 0 4px;
  border-radius: 999px;
  outline: none;
  appearance: none;
  background: linear-gradient(90deg, var(--portal-accent), var(--portal-line));
  cursor: pointer;
}

.timeline-range::-webkit-slider-thumb {
  width: 14px;
  height: 14px;
  border: 2px solid var(--portal-bg);
  border-radius: 50%;
  appearance: none;
  background: var(--portal-accent);
  box-shadow: 0 0 0 3px var(--portal-accent-soft), 0 0 12px rgba(55, 213, 242, 0.55);
}

.timeline-range::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border: 2px solid var(--portal-bg);
  border-radius: 50%;
  background: var(--portal-accent);
  box-shadow: 0 0 0 3px var(--portal-accent-soft), 0 0 12px rgba(55, 213, 242, 0.55);
}

.flight-log-panel-shell,
.right-panel-group {
  top: 88px;
}

.flight-log-tip {
  color: var(--portal-text-dim);
  line-height: 1.55;
  opacity: 1;
}

.flight-log-panel-shell select[multiple] {
  border: 1px solid var(--portal-line);
  border-radius: 10px;
  outline: 0;
  background: var(--portal-panel-strong);
  color: var(--portal-text);
  font-family: "SF Mono", "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
}

.flight-log-panel-shell select[multiple] option {
  padding: 8px;
  border-radius: 6px;
}

.flight-log-panel-shell select[multiple] option:checked {
  background: linear-gradient(var(--portal-accent-soft), var(--portal-accent-soft));
  color: var(--portal-accent);
}

.panel {
  position: relative;
  border: 1px solid var(--portal-line);
  border-radius: 16px;
  background: var(--portal-panel);
  box-shadow: var(--portal-shadow);
  backdrop-filter: blur(16px) saturate(125%);
}

.panel-header {
  min-height: 42px;
  padding: 8px 12px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--portal-line);
  background: var(--portal-panel-soft);
  color: var(--portal-text);
  letter-spacing: 0.04em;
}

.panel-tab {
  border-color: transparent;
  background: transparent;
  color: var(--portal-text-dim);
}

.panel-tab.active {
  border-color: var(--portal-accent);
  background: var(--portal-accent-soft);
  color: var(--portal-accent);
}

.panel-body {
  padding: 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--portal-text-faint) transparent;
}

.panel-header button {
  padding: 4px 9px;
  border: 1px solid var(--portal-line);
  border-radius: 8px;
  background: transparent;
  color: var(--portal-text-dim);
}

.panel-header button:hover {
  border-color: var(--portal-accent);
  color: var(--portal-accent);
}

.panel-collapse-handle {
  border: 1px solid var(--portal-line);
  border-right: 0;
  border-radius: 14px 0 0 14px;
  background: var(--portal-panel-strong);
  box-shadow: var(--portal-shadow);
  color: var(--portal-text-dim);
  backdrop-filter: blur(16px);
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.panel-collapse-handle:hover {
  border-color: var(--portal-accent);
  background: var(--portal-panel-soft);
  color: var(--portal-accent);
}

.flight-log-collapse-handle {
  border-right: 1px solid var(--portal-line);
  border-left: 0;
  border-radius: 0 14px 14px 0;
}

.info-grid {
  gap: 7px 14px;
  line-height: 1.35;
}

.info-label {
  color: var(--portal-text-dim);
  font-weight: 600;
  opacity: 1;
}

.info-value {
  color: var(--portal-text);
  font-family: "SF Mono", "JetBrains Mono", Consolas, monospace;
  font-variant-numeric: tabular-nums;
}

.metric-description p,
.metric-description ul {
  color: var(--portal-text-dim);
  line-height: 1.55;
}

.metric-description :deep(font) {
  color: inherit;
}

.metric-description .good { color: #4ade80; }
.metric-description .normal { color: #a3e635; }
.metric-description .poor { color: #fbbf24; }
.metric-description .bad { color: #f87171; }

.chart-panel-header {
  min-height: 42px;
  padding: 8px 14px;
  box-sizing: border-box;
  border: 1px solid var(--portal-line);
  border-bottom: 0;
  border-radius: 16px 16px 0 0;
  background: var(--portal-panel-soft);
  backdrop-filter: blur(16px);
}

.chart-panel-header span {
  color: var(--portal-text);
  letter-spacing: 0.08em;
}

.chart-panel-header button,
.chart-collapse-handle {
  border: 1px solid var(--portal-line);
  border-radius: 8px;
  background: var(--portal-accent-soft);
  color: var(--portal-accent);
}

.chart-collapse-handle {
  border-radius: 14px;
  background: var(--portal-panel-strong);
  box-shadow: var(--portal-shadow);
  backdrop-filter: blur(16px);
}

.chart {
  border: 1px solid var(--portal-line);
  border-radius: 0 0 16px 16px;
  background: var(--portal-panel);
  box-shadow: var(--portal-shadow);
  backdrop-filter: blur(16px);
}

@media (max-width: 1200px) {
  .flight-log-panel-shell,
  .right-panel-group {
    top: 150px;
  }
}

@media (max-width: 900px) {
  .floating-toolbar {
    top: 10px;
    left: 10px;
    right: 10px;
  }

  .flight-log-panel-shell {
    top: 146px;
  }

  .right-panel-group {
    top: auto;
  }
}
</style>

<style>
html,
body,
#app {
  width: 100%;
  height: 100%;
  margin: 0;
}

body {
  overflow: hidden;
}

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
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.2);
}
.change-marker-dot {
  width: 7px;
  height: 7px;
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
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(224, 242, 254, 0.96);
  border: 1px solid rgba(125, 211, 252, 0.8);
  /* box-shadow: 0 8px 20px rgba(15, 23, 42, 0.18); */
}
.change-marker-dot-only.cell-id-marker {
  background: rgba(224, 242, 254, 0.96);
  border-color: rgba(125, 211, 252, 0.8);
}
.change-marker-dot-only.cell-id-marker .change-marker-dot {
  background: #38bdf8;
}
.change-marker-dot-only.pci-marker {
  background: rgba(191, 219, 254, 0.96);
  border-color: rgba(59, 130, 246, 0.8);
}
.change-marker-dot-only.pci-marker .change-marker-dot {
  background: #1d4ed8;
}
.change-marker.cell-id-marker {
  color: #0284c7;
  background: rgba(224, 242, 254, 0.96);
}
.change-marker.cell-id-marker .change-marker-dot {
  background: #38bdf8;
}
.change-marker.pci-marker {
  color: #1d4ed8;
  background: rgba(191, 219, 254, 0.96);
}
.change-marker.pci-marker .change-marker-dot {
  background: #1d4ed8;
}
</style>
