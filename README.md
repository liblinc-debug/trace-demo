# 根据无人机飞行记录，在地图上回放飞行过程

## 功能要求概述：
1. 无人机实际飞行记录在 "无人机08_yyyyMMdd_HHmmss_Flight.csv"文件中；
2. 希望根据无人机实际飞行记录文件在“高德地图”上生成飞行轨迹， 并且可以播放飞行动画；

## 地图上的主要功能：
1. 通过“下拉选择框”选择具体的“无人机实际飞行记录文件”；
2. 有播放、暂停、进度条（可在进度条上拖动）来控制对应的无人机位置；
3. 地图上用”四旋翼“无人机图标，展示无人机所在位置；
4. 轨迹线根据点位信息，以”浅兰色“线段展示所有的轨迹线；
5. 地图可以展示3D视角，在 3D视角中，轨迹线与无人机位置需要根据”Altitude(m)“数据显示对应的高度；
6. 在地图下方使用拆线图在同一个坐标系中展示以下指标：Loss_Rate(%),Avg_Ping(ms),Dist_to_Arm_Pt(m)，分别为丢包率、ping值、距离；默认展示所有时间维度上的数据，在拆线图中通过一条垂直虚线与当前无人机飞行时的时间相对应，标记当前无人机飞行时所对应的监测数据；

## 技术要求：
1. 使用 nodejs 开发
2. 前端使用 VUE 架构
3. 使用高德地图 API 展示，在配置文件中定义高德地图 web 端 API KEY
4. 根据 VUE架构要求，组织好工程目录，并且整理好相关安装脚本与启动脚本

---

## 运行说明

1. 在项目根目录执行 `npm install` 安装依赖。
2. 编辑 `.env` 文件，将 `VITE_AMAP_KEY` 替换为自己的高德 Web API KEY。
3. 开发时运行 `npm run dev` 将同时启动前端开发服务器和后端接口，后者监听 3000 端口。
4. 接口说明：
   - `GET /api/logs` 返回可供选择的 CSV 文件列表。
   - `GET /api/logs/:name` 下载指定日志文件。

5. 生产构建：`npm run build` 会生成静态文件到 `dist`。
   使用 `npm start` 启动服务器，或者将 `dist` 部署至静态托管服务。

## 目录结构

```raw
trace-demo/
├── logs/                  # 飞行记录文件
├── src/                   # Vue 应用源码
│   ├── App.vue
│   └── main.js
├── server.js              # Express 后端
├── vite.config.js
├── package.json
├── .env                   # 环境变量（API KEY）
└── README.md
```

---

## 功能优化改进

1. 增加新指标：Signal_dBm、Jitter(ms)数据在 坐标系中的展示，并且注意对原数据结构的兼容，即没有相应指标数据时不展示该指标的图表；
2. 播放速度增加：4X、8X、16X 速度的选项，选择对应速度后，根据倍数进行动画的播放数据；
3. 整体界面风格增加白天与黑夜两种风格，根据选择的风格对界面进行不同风格的设置；
4. 图表上默认展示Ping值与 Signal 两个指标，其他指标点击后再展示；
5. 在图表上点击时，地图上的动画展示的时间点保持与在图表上点击的时间点一至，方便查看某个指标数据异常时，观察无人机此时所在的位置；
6. 显示一个半透明浮动层展示无人机的实时信息：包括以下指标：Timestamp	Latitude	Longitude	Altitude(m)	Speed(m/s)	Climb(m/s)	Heading(deg)	Loss_Rate(%)	Avg_Ping(ms)	Dist_to_Arm_Pt(m)	Flight_Dist(m)	WP_Speed(m/s)	WP_Radius(m)	WP_Accel(m/s2)	Network	Band	Signal_dBm	RSRP	RSRQ	SNR	RSSI	Jitter(ms)，要求排列整齐，展示在右上角，不要太大的图层
7. 其他功能保持原功能状态；

