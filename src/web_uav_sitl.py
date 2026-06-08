import sys
import math
import asyncio
import json
import threading
import time
import os
import datetime
import subprocess
import platform
import re

# 强制设置环境变量开启 MAVLink 2.0
os.environ["MAVLINK20"] = "1" 

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pymavlink import mavutil
import paho.mqtt.client as mqtt

# ==========================================
# 全局状态配置
# ==========================================
GLOBAL_STATE = {
    "anti_collision": False, 
    "collision_radius": 5.0  
}

# ==========================================
# 1. 坐标转换工具
# ==========================================
class EvilTransform:
    pi = 3.1415926535897932384626
    a = 6378245.0
    ee = 0.00669342162296594323
    @classmethod
    def delta(cls, lat, lon):
        dLat = cls.transformLat(lon - 105.0, lat - 35.0)
        dLon = cls.transformLon(lon - 105.0, lat - 35.0)
        radLat = lat / 180.0 * cls.pi
        magic = math.sin(radLat)
        magic = 1 - cls.ee * magic * magic
        sqrtMagic = math.sqrt(magic)
        dLat = (dLat * 180.0) / ((cls.a * (1 - cls.ee)) / (magic * sqrtMagic) * cls.pi)
        dLon = (dLon * 180.0) / (cls.a / sqrtMagic * math.cos(radLat) * cls.pi)
        return dLat, dLon
    @classmethod
    def transformLat(cls, x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * cls.pi) + 20.0 * math.sin(2.0 * x * cls.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * cls.pi) + 40.0 * math.sin(y / 3.0 * cls.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * cls.pi) + 320 * math.sin(y * cls.pi / 30.0)) * 2.0 / 3.0
        return ret
    @classmethod
    def transformLon(cls, x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * cls.pi) + 20.0 * math.sin(2.0 * x * cls.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * cls.pi) + 40.0 * math.sin(x / 3.0 * cls.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * cls.pi) + 300.0 * math.sin(x / 30.0 * cls.pi)) * 2.0 / 3.0
        return ret
    @classmethod
    def wgs2gcj(cls, wgsLat, wgsLon):
        if not (72.004 <= wgsLon <= 137.8347 and 0.8293 <= wgsLat <= 55.8271): return wgsLat, wgsLon
        dLat, dLon = cls.delta(wgsLat, wgsLon)
        return wgsLat + dLat, wgsLon + dLon
    @classmethod
    def gcj2wgs(cls, gcjLat, gcjLon):
        if not (72.004 <= gcjLon <= 137.8347 and 0.8293 <= gcjLat <= 55.8271): return gcjLat, gcjLon
        dLat, dLon = cls.delta(gcjLat, gcjLon)
        return gcjLat - dLat, gcjLon - dLon
    @classmethod
    def get_distance_meters(cls, lat1, lon1, lat2, lon2):
        if lat1 == 0 or lat2 == 0: return 0.0
        radLat1 = lat1 * cls.pi / 180.0
        radLat2 = lat2 * cls.pi / 180.0
        a = radLat1 - radLat2
        b = (lon1 - lon2) * cls.pi / 180.0
        s = 2 * math.asin(math.sqrt(math.pow(math.sin(a / 2), 2) + math.cos(radLat1) * math.cos(radLat2) * math.pow(math.sin(b / 2), 2)))
        s = s * 6378137.0
        return s

# ==========================================
# 2. 无人机节点管理 
# ==========================================
MQTT_USER = "szetst"
MQTT_PASS = "Etst@2025"

class DroneNode:
    def __init__(self, config):
        self.config = config
        self.id = config["id"]
        
        # 飞行状态
        self.lat = 0.0; self.lon = 0.0; self.alt = 0.0; self.rel_alt = 0.0
        self.home_lat = 0.0; self.home_lon = 0.0
        self.heading = 0.0; self.spd = 0.0; self.climb = 0.0
        self.batt = 0.0; self.fix_type = 0; self.sats = 0; self.hdop = 99.9
        self.mode = "WAITING"; self.armed = False; self.connected = False
        
        # 幽灵预测模式的目标坐标
        self.target_lat = 0.0
        self.target_lon = 0.0
        self.target_alt = 0.0

        # 云台状态
        self.gimbal_yaw = 0.0; self.gimbal_pitch = 0.0; self.gimbal_roll = 0.0
        self.sim_gimbal_x = 0.0; self.sim_gimbal_y = 0.0
        
        # 暂停与防撞状态记忆
        self.pre_pause_mode = None
        self.last_guided_cmd = None
        self.is_yielding = False 
        self.ignore_collision_until_safe = False 
        
        # 避让专属坐标缓存
        self.evade_target_lat = None
        self.evade_target_lon = None
        self.evade_target_alt = None
        
        # 解锁点与 Ping 缓存
        self.arm_lat = 0.0
        self.arm_lon = 0.0
        self.ping_rtts = []
        self.avg_ping_ms = 0.0
        
        # 精准秒级丢包率统计
        self.last_seq = None
        self.packets_lost_in_sec = 0
        self.packets_received_in_sec = 0
        self.sec_start_time = time.time()
        self.hb_loss_rate = 0.0
        self.last_hb_log = ""
        self.hb_log_updated = False
        
        # 【新增】：飞控系统文本报错状态
        self.last_status_text = ""
        self.status_text_updated = False

        # 通信句柄与锁
        self.mav_conn = None
        self.mqtt_client = None
        self.running = True
        self.uploading_mission = False 

        self.log_dir = "flight_logs"
        os.makedirs(self.log_dir, exist_ok=True)
        self.current_log_filename = None

        threading.Thread(target=self.mavlink_worker, daemon=True).start()
        threading.Thread(target=self.mqtt_worker, daemon=True).start()
        threading.Thread(target=self.logging_worker, daemon=True).start()
        threading.Thread(target=self.icmp_ping_worker, daemon=True).start()

    def disconnect_node(self):
        self.running = False 
        self.connected = False
        print(f"🛑 正在断开并清理 {self.id} 的连接资源...")
        if self.mav_conn:
            try:
                self.mav_conn.close()
            except: pass
        if getattr(self, 'mqtt_client', None):
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except: pass

    def get_target_ip(self):
        match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", self.config.get('fcu_url', ''))
        if match: return match.group(1)
        match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", self.config.get('mqtt_ip', ''))
        if match: return match.group(1)
        return None

    def icmp_ping_worker(self):
        target_ip = self.get_target_ip()
        if not target_ip:
            self.avg_ping_ms = 0.0
            return

        is_win = platform.system().lower() == 'windows'
        param = '-n' if is_win else '-c'
        timeout_param = '-w' if is_win else '-W'
        timeout_val = '1000' if is_win else '1'

        while self.running:
            try:
                command = ['ping', param, '1', timeout_param, timeout_val, target_ip]
                output_bytes = subprocess.check_output(command, stderr=subprocess.STDOUT, timeout=2.0)
                
                try:
                    output = output_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    output = output_bytes.decode('gbk', errors='ignore')

                match = re.search(r'(?:time|时间|tiempo)[=<]\s*([\d.]+)', output, re.IGNORECASE)
                
                if match:
                    rtt = float(match.group(1))
                    self.ping_rtts.append(rtt)
                    if len(self.ping_rtts) > 5: 
                        self.ping_rtts.pop(0)
                    self.avg_ping_ms = sum(self.ping_rtts) / len(self.ping_rtts)
                else:
                    self.avg_ping_ms = 999.0 
            except Exception:
                self.avg_ping_ms = 999.0 
                
            time.sleep(1.0) 

    def logging_worker(self):
        while self.running:
            time.sleep(1.0) 
            if self.connected and self.armed and self.lat != 0 and self.current_log_filename:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                dist_arm = 0.0
                if self.arm_lat != 0 and self.arm_lon != 0:
                    dist_arm = EvilTransform.get_distance_meters(self.lat, self.lon, self.arm_lat, self.arm_lon)
                
                log_line = f"{timestamp},{self.lat:.7f},{self.lon:.7f},{self.rel_alt:.1f},{self.spd:.1f},{self.heading:.1f},{self.hb_loss_rate:.1f},{self.avg_ping_ms:.1f},{dist_arm:.1f}\n"
                try:
                    with open(self.current_log_filename, "a", encoding="utf-8") as f:
                        f.write(log_line)
                except Exception:
                    pass

    def send_hover_command(self):
        self.set_mode("GUIDED")
        if self.mav_conn:
            self.mav_conn.mav.set_position_target_local_ned_send(
                0, self.mav_conn.target_system, self.mav_conn.target_component,
                mavutil.mavlink.MAV_FRAME_LOCAL_NED, 
                0b0000111111000111, 
                0, 0, 0,  
                0, 0, 0,  
                0, 0, 0,  
                0, 0      
            )

    def pause_flight(self):
        if not getattr(self, 'is_yielding', False):
            self.pre_pause_mode = self.mode
        self.send_hover_command()

    def resume_flight(self):
        target_mode = getattr(self, 'pre_pause_mode', 'AUTO')
        if target_mode not in ["AUTO", "GUIDED"]:
            target_mode = "AUTO"
        
        self.set_mode(target_mode)
        
        if target_mode == "GUIDED" and getattr(self, 'last_guided_cmd', None):
            threading.Thread(target=self._delayed_resume_guided).start()

    def _delayed_resume_guided(self):
        time.sleep(0.3)
        gc = getattr(self, 'last_guided_cmd', None)
        if gc:
            self.fly_guided(gc["lat"], gc["lon"], gc["alt"], gc["speed"], gc["yaw"])

    def mavlink_worker(self):
        while self.running:
            try:
                fcu_url = self.config['fcu_url']
                baudrate = int(self.config.get('baudrate', 57600))
                
                if fcu_url.lower().startswith(('udp', 'tcp')):
                    self.mav_conn = mavutil.mavlink_connection(fcu_url, source_system=255)
                else:
                    self.mav_conn = mavutil.mavlink_connection(fcu_url, baud=baudrate, source_system=255)
                
                print(f"⏳ {self.id} 等待飞控心跳包...")
                self.mav_conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID, 
                    0, 0, 0
                )

                hb = self.mav_conn.wait_heartbeat(timeout=5)
                if not hb:
                    if self.running:
                        print(f"⚠️ {self.id} 未收到心跳包，准备重试...")
                        time.sleep(2)
                    continue

                self.connected = True
                self.connection_start_time = time.time()
                print(f"✅ {self.id} MAVLink 连接成功! ({fcu_url})")
                
                self.mav_conn.mav.request_data_stream_send(
                    self.mav_conn.target_system,
                    self.mav_conn.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL, 
                    10, 1
                )
                
                self.last_seq = None
                self.sec_start_time = time.time()
                self.packets_lost_in_sec = 0
                self.packets_received_in_sec = 0
                
                while self.running and self.connected:
                    if getattr(self, 'uploading_mission', False):
                        time.sleep(0.05)
                        continue
                        
                    current_time = time.time()

                    msg = self.mav_conn.recv_match(blocking=True, timeout=0.1)
                    if not msg: 
                        if current_time - self.sec_start_time >= 1.0:
                            self.hb_loss_rate = 100.0
                            self.packets_lost_in_sec = 0
                            self.packets_received_in_sec = 0
                            self.sec_start_time = current_time
                        continue
                    
                    try:
                        seq = msg.get_seq()
                        if self.last_seq is not None:
                            drop = (seq - self.last_seq - 1) % 256
                            if drop < 100:  
                                self.packets_lost_in_sec += drop
                        self.last_seq = seq
                        self.packets_received_in_sec += 1
                    except Exception:
                        pass
                    
                    if current_time - self.sec_start_time >= 1.0:
                        total = self.packets_received_in_sec + self.packets_lost_in_sec
                        if total > 0:
                            self.hb_loss_rate = round((self.packets_lost_in_sec / total) * 100.0, 1)
                        else:
                            self.hb_loss_rate = 100.0
                        self.packets_lost_in_sec = 0
                        self.packets_received_in_sec = 0
                        self.sec_start_time = current_time

                    mtype = msg.get_type()
                                
                    if mtype == 'HEARTBEAT':
                        new_armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
                        
                        if new_armed and not self.armed:
                            self.arm_lat = self.lat
                            self.arm_lon = self.lon
                            readable_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_name = self.config.get('name', 'Drone').replace(" ", "_")
                            self.current_log_filename = os.path.join(self.log_dir, f"{safe_name}_{readable_time}_Flight.csv")
                            try:
                                with open(self.current_log_filename, "w", encoding="utf-8") as f:
                                    f.write("Timestamp,Latitude,Longitude,Altitude(m),Speed(m/s),Heading(deg),Loss_Rate(%),Avg_Ping(ms),Dist_to_Arm_Pt(m)\n")
                                print(f"🛫 {self.id} 已解锁，开始记录架次日志: {self.current_log_filename}")
                            except: pass
                        elif not new_armed and self.armed:
                            self.current_log_filename = None
                            
                        self.armed = new_armed
                        self.mode = mavutil.mode_string_v10(msg)
                        
                        hb_log_str = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 💓 {self.id} 心跳包: 模式={self.mode}, 解锁={'是' if self.armed else '否'}"
                        self.last_hb_log = hb_log_str
                        self.hb_log_updated = True

                    # 【新增解析】：抓取底层飞控的弹窗警告文本 (PreArm 等报错)
                    elif mtype == 'STATUSTEXT':
                        text = msg.text
                        # severity <= 4 代表这是 Warning/Error/Critical 级别的严重消息
                        if "PreArm" in text or msg.severity <= 4:
                            self.last_status_text = text
                            self.status_text_updated = True

                    elif mtype == 'GLOBAL_POSITION_INT':
                        self.lat = msg.lat / 1e7
                        self.lon = msg.lon / 1e7
                        self.rel_alt = msg.relative_alt / 1000.0
                        self.alt = msg.alt / 1000.0
                        self.heading = msg.hdg / 100.0
                    elif mtype == 'VFR_HUD':
                        self.spd = msg.groundspeed
                        self.climb = msg.climb
                    elif mtype == 'SYS_STATUS':
                        self.batt = msg.voltage_battery / 1000.0
                    elif mtype == 'GPS_RAW_INT':
                        self.fix_type = msg.fix_type
                        self.sats = msg.satellites_visible
                        self.hdop = msg.eph / 100.0
                    elif mtype == 'HOME_POSITION':
                        self.home_lat = msg.latitude / 1e7
                        self.home_lon = msg.longitude / 1e7
                        
                    elif mtype == 'POSITION_TARGET_GLOBAL_INT':
                        if msg.lat_int != 0 and msg.lon_int != 0:
                            self.target_lat = msg.lat_int / 1e7
                            self.target_lon = msg.lon_int / 1e7
                            self.target_alt = msg.alt
                        
            except Exception as e:
                self.connected = False
                if self.running:
                    print(f"⚠️ {self.id} MAVLink 断开重连中... ({e})")
                    time.sleep(3)

    def send_command_long(self, command, param1=0, param2=0, param3=0, param4=0, param5=0, param6=0, param7=0):
        if self.mav_conn:
            self.mav_conn.mav.command_long_send(self.mav_conn.target_system, self.mav_conn.target_component, command, 0, param1, param2, param3, param4, param5, param6, param7)

    def set_mode(self, mode_name):
        if not self.mav_conn: return
        mode_id = self.mav_conn.mode_mapping().get(mode_name)
        if mode_id is not None:
            self.mav_conn.mav.set_mode_send(self.mav_conn.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_id)

    def upload_mission(self, waypoints):
        if not self.mav_conn: return
        print(f"📤 {self.id} 开始上传 {len(waypoints)} 个航点...")
        self.uploading_mission = True
        time.sleep(0.2)
        try:
            self.mav_conn.mav.mission_clear_all_send(self.mav_conn.target_system, self.mav_conn.target_component)
            time.sleep(0.5)
            self.mav_conn.mav.mission_count_send(self.mav_conn.target_system, self.mav_conn.target_component, len(waypoints) + 1)
            req = self.mav_conn.recv_match(type=['MISSION_REQUEST', 'MISSION_REQUEST_INT'], blocking=True, timeout=3.0)
            if not req: return
            self.mav_conn.mav.mission_item_int_send(self.mav_conn.target_system, self.mav_conn.target_component, 0, mavutil.mavlink.MAV_FRAME_GLOBAL, 16, 1, 1, 0, 0, 0, 0, int(self.lat*1e7), int(self.lon*1e7), self.alt)
            for i, wp in enumerate(waypoints):
                seq = i + 1
                req = self.mav_conn.recv_match(type=['MISSION_REQUEST', 'MISSION_REQUEST_INT'], blocking=True, timeout=3.0)
                if not req: break
                cmd_id = {"WAYPOINT": 16, "TAKEOFF": 22, "RTL": 20, "LAND": 21}.get(wp['cmd'], 16)
                self.mav_conn.mav.mission_item_int_send(self.mav_conn.target_system, self.mav_conn.target_component, seq, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, cmd_id, 0, 1, 0, 0, 0, 0, int(wp['lat']*1e7), int(wp['lon']*1e7), float(wp['alt']))
            ack = self.mav_conn.recv_match(type='MISSION_ACK', blocking=True, timeout=3.0)
            if ack and ack.type == 0: print(f"✅ {self.id} 航点上传成功!")
        except Exception as e:
            print(f"❌ {self.id} 航点上传异常: {e}")
        finally:
            self.uploading_mission = False

    def download_mission(self):
        if not self.mav_conn: return []
        print(f"📥 {self.id} 开始下载航点...")
        self.uploading_mission = True
        time.sleep(0.2)
        wps = []
        try:
            self.mav_conn.mav.mission_request_list_send(self.mav_conn.target_system, self.mav_conn.target_component)
            msg = self.mav_conn.recv_match(type='MISSION_COUNT', blocking=True, timeout=3.0)
            if not msg: return []
            count = msg.count
            for i in range(count):
                self.mav_conn.mav.mission_request_int_send(self.mav_conn.target_system, self.mav_conn.target_component, i)
                item = self.mav_conn.recv_match(type=['MISSION_ITEM_INT', 'MISSION_ITEM'], blocking=True, timeout=3.0)
                if not item: break
                if i == 0: continue 
                cmd_name = {16: "WAYPOINT", 22: "TAKEOFF", 20: "RTL", 21: "LAND"}.get(item.command, "WAYPOINT")
                lat = (item.x / 1e7) if hasattr(item, 'x') else item.lat
                lon = (item.y / 1e7) if hasattr(item, 'y') else item.lon
                alt = item.z if hasattr(item, 'z') else item.alt
                wps.append({'cmd': cmd_name, 'lat': lat, 'lon': lon, 'alt': alt})
            self.mav_conn.mav.mission_ack_send(self.mav_conn.target_system, self.mav_conn.target_component, 0)
            print(f"✅ {self.id} 航点下载完成!")
            return wps
        except Exception as e:
            print(f"❌ {self.id} 航点下载异常: {e}")
            return []
        finally:
            self.uploading_mission = False

    def fly_guided(self, lat, lon, alt, speed=5.0, yaw_deg=0):
        if not self.mav_conn: return
        self.set_mode("GUIDED")
        time.sleep(0.2)
        self.send_command_long(mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED, 1, speed, -1, 0, 0, 0, 0)
        yaw_rad = math.radians(yaw_deg)
        self.mav_conn.mav.set_position_target_global_int_send(0, self.mav_conn.target_system, self.mav_conn.target_component, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, 0b0000111111111000, int(lat*1e7), int(lon*1e7), float(alt), 0, 0, 0, 0, 0, 0, yaw_rad, 0)

    def mqtt_worker(self):
        while self.running:
            try:
                if hasattr(self, 'mqtt_client') and self.mqtt_client:
                    self.mqtt_client.loop_stop()
                client_id = f"GCS_V3_{self.id}_{int(time.time())}"
                
                try:
                    from paho.mqtt.enums import CallbackAPIVersion
                    self.mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION1, client_id=client_id, protocol=mqtt.MQTTv311)
                except Exception:
                    self.mqtt_client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
                    
                self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
                self.mqtt_client.connect_async(self.config['mqtt_ip'], 1883, keepalive=60)
                self.mqtt_client.loop_start() 
                print(f"✅ {self.id} MQTT 连接指令已发出...")
                break 
            except Exception as e:
                if self.running:
                    print(f"❌ {self.id} MQTT 失败: {e}，重试中...")
                    time.sleep(2)

    def send_gimbal_cmd(self, action, val1=None, val2=None):
        if not self.mqtt_client: return
        topic = "siyi/a8mini/control"
        if action in ["up", "down", "left", "right", "center", "stop"]:
            payload_dict = {"command": action}
        elif action == "zoom":
            payload_dict = {"command": "manual_zoom", "zoom": int(val1)}
        elif action == "set_angle":
            payload_dict = {"command": "set_angle", "yaw": float(val1), "pitch": float(val2)}
        else: return
        payload_str = json.dumps(payload_dict, separators=(',', ':'))
        info = self.mqtt_client.publish(topic, payload_str)
        try: info.wait_for_publish(timeout=0.5)
        except: pass     

nodes = {}

# ==========================================
# 2.5 防撞避让后台线程 (Swarm Anti-Collision)
# ==========================================
def anti_collision_worker():
    while True:
        time.sleep(0.1) 
        
        if not GLOBAL_STATE.get("anti_collision", False):
            for node in nodes.values():
                if getattr(node, 'is_yielding', False):
                    node.is_yielding = False
                    node.resume_flight()
            continue
        
        active_drones = [n for n in nodes.values() if n.connected and n.lat != 0]
        
        def get_priority(n):
            mode_priority = 1 if n.mode in ["AUTO", "GUIDED"] else 0
            return (mode_priority, n.id)
            
        active_drones.sort(key=get_priority)
        
        current_radius = GLOBAL_STATE.get("collision_radius", 5.0)
        
        for i, node in enumerate(active_drones):
            if node.mode not in ["AUTO", "GUIDED"]:
                if getattr(node, 'is_yielding', False):
                    node.is_yielding = False
                    node.ignore_collision_until_safe = False
                continue
                
            should_yield = False
            
            for j in range(i):
                other = active_drones[j]
                dist_2d = EvilTransform.get_distance_meters(node.lat, node.lon, other.lat, other.lon)
                
                if dist_2d < current_radius:
                    should_yield = True
                    break
                    
            if should_yield:
                if getattr(node, 'ignore_collision_until_safe', False):
                    continue 
                
                if not getattr(node, 'is_yielding', False):
                    node.is_yielding = True
                    node.pre_pause_mode = node.mode
                    print(f"⚠️ 防撞触发: {node.id} 进入避让悬停！(水平距离: {dist_2d:.1f}m < {current_radius}m)")
                
                node.send_hover_command()
                
            else:
                if getattr(node, 'is_yielding', False):
                    node.is_yielding = False
                    node.resume_flight()
                    print(f"✅ 安全恢复: {node.id} 恢复飞行！")
                
                if getattr(node, 'ignore_collision_until_safe', False):
                    node.ignore_collision_until_safe = False

threading.Thread(target=anti_collision_worker, daemon=True).start()


# ==========================================
# 3. FastAPI & WebSocket 路由
# ==========================================
app = FastAPI()

os.makedirs("offline_tiles", exist_ok=True)
app.mount("/tiles", StaticFiles(directory="offline_tiles"), name="tiles")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    async def send_telemetry():
        while True:
            telemetry_data = {}
            for d_id, node in list(nodes.items()):
                glat, glon = EvilTransform.wgs2gcj(node.lat, node.lon)
                dist_home = EvilTransform.get_distance_meters(node.lat, node.lon, node.home_lat, node.home_lon)
                
                t_glat, t_glon = EvilTransform.wgs2gcj(node.target_lat, node.target_lon) if node.target_lat != 0 else (0, 0)

                telemetry_data[d_id] = {
                    "name": node.config.get("name"),
                    "rtsp_url": node.config.get("rtsp_url"),
                    "lat": glat, "lon": glon, "alt": node.rel_alt,
                    "heading": node.heading, "spd": node.spd, "climb": node.climb,
                    "batt": node.batt, "fix": node.fix_type, "sats": node.sats, "hdop": node.hdop,
                    "mode": node.mode, "armed": "ARMED" if node.armed else "DISARMED",
                    "connected": node.connected, "dist_home": dist_home,
                    "gimbal_yaw": node.gimbal_yaw, "gimbal_pitch": node.gimbal_pitch,
                    "hb_loss_rate": node.hb_loss_rate,
                    "avg_ping_ms": node.avg_ping_ms, 
                    "yielding": getattr(node, 'is_yielding', False),
                    "target_lat": t_glat,
                    "target_lon": t_glon
                }
                if getattr(node, 'hb_log_updated', False):
                    telemetry_data[d_id]["hb_log"] = node.last_hb_log
                    node.hb_log_updated = False
                
                # 【新增】：将抓到的飞控文本发送给前端弹窗
                if getattr(node, 'status_text_updated', False):
                    telemetry_data[d_id]["status_text"] = node.last_status_text
                    node.status_text_updated = False
                    
            try:
                await websocket.send_json({"type": "telemetry", "data": telemetry_data})
                await asyncio.sleep(0.5)
            except:
                break

    task = asyncio.create_task(send_telemetry())
    
    try:
        while True:
            msg = await websocket.receive_json()
            cmd = msg.get("command")
            
            if cmd == "REMOVE_DRONE":
                d_id = msg.get("drone_id")
                if d_id in nodes:
                    nodes[d_id].disconnect_node()
                    del nodes[d_id]
                    print(f"🗑️ 已成功移除无人机节点: {d_id}")
                continue

            if cmd == "TOGGLE_ANTI_COLLISION":
                GLOBAL_STATE["anti_collision"] = msg.get("enabled", False)
                GLOBAL_STATE["collision_radius"] = float(msg.get("radius", 5.0))
                print(f"🛡️ 防撞避让已 {'开启' if GLOBAL_STATE['anti_collision'] else '关闭'}，避让半径设定为: {GLOBAL_STATE['collision_radius']}m")
                continue
            
            if cmd == "ADD_DRONE":
                new_id = f"drone_{int(time.time())}"
                nodes[new_id] = DroneNode({
                    "id": new_id,
                    "name": msg.get("name", "New Drone"),
                    "fcu_url": msg.get("fcu_url"),
                    "baudrate": msg.get("baudrate", 57600),
                    "rtsp_url": msg.get("rtsp_url"),
                    "mqtt_ip": msg.get("mqtt_ip")
                })
                print(f"🆕 添加新无人机: {new_id} - {msg.get('name')}")
                continue

            d_id = msg.get("drone_id")
            node = nodes.get(d_id)
            if not node: continue

            # 普通解锁
            if cmd == "ARM": 
                node.send_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            # 【新增】：强制解锁 (魔法数字 21196 会绕过所有 PreArm Check 强行解锁)
            elif cmd == "FORCE_ARM": 
                node.send_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, 21196)
                
            elif cmd == "DISARM": 
                node.send_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0)
                
            elif cmd == "MODE": node.set_mode(msg.get("val"))
            elif cmd == "TAKEOFF": 
                node.set_mode("GUIDED")
                time.sleep(0.3)
                node.send_command_long(22, 0, 0, 0, 0, 0, 0, float(msg.get("val", 10)))
                
            elif cmd == "START_MISSION": 
                node.ignore_collision_until_safe = True
                node.is_yielding = False
                node.set_mode("AUTO")
                node.send_command_long(mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0, 0, 0, 0, 0, 0)
                print(f"🚀 强行发车: {node.id} 开始任务，暂时屏蔽防撞！")
            
            elif cmd == "PAUSE":
                node.ignore_collision_until_safe = False
                node.pause_flight()
                
            elif cmd == "RESUME":
                node.ignore_collision_until_safe = True
                node.is_yielding = False
                node.resume_flight()
                print(f"🚀 人工干预: {node.id} 强行恢复飞行，暂时屏蔽防撞！")

            elif cmd == "YAW":
                step = float(msg.get("val", 10))
                target_compass = (node.heading + step) % 360
                yaw_rad = math.radians(90 - target_compass)
                node.send_command_long(115, target_compass, 0, 1, 0)
            elif cmd == "YAW_ABS":
                target_deg = float(msg.get("val", 0))
                node.send_command_long(115, target_deg, 0, 0, 0)
                
            elif cmd == "GUIDED_FLY":
                wgs_lat, wgs_lon = EvilTransform.gcj2wgs(msg.get("lat"), msg.get("lon"))
                alt = float(msg.get("alt", 30))
                speed = float(msg.get("speed", 5))
                yaw = float(msg.get("yaw", 0))
                
                node.last_guided_cmd = {"lat": wgs_lat, "lon": wgs_lon, "alt": alt, "speed": speed, "yaw": yaw}
                node.fly_guided(wgs_lat, wgs_lon, alt, speed, yaw)
            
            elif cmd == "MOVE_RELATIVE":
                if not node.mav_conn: continue
                node.set_mode("GUIDED")
                time.sleep(0.1)
                dx = float(msg.get("dx", 0)) 
                dy = float(msg.get("dy", 0)) 
                dz = float(msg.get("dz", 0)) 
                
                node.mav_conn.mav.set_position_target_local_ned_send(
                    0, node.mav_conn.target_system, node.mav_conn.target_component,
                    mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED, 0b0000111111111000, 
                    dx, dy, dz, 0, 0, 0, 0, 0, 0, 0, 0
                )

            elif cmd == "UPLOAD_MISSION":
                wps = msg.get("waypoints", [])
                for wp in wps: wp['lat'], wp['lon'] = EvilTransform.gcj2wgs(wp['lat'], wp['lon'])
                threading.Thread(target=node.upload_mission, args=(wps,)).start()
            
            elif cmd == "DOWNLOAD_MISSION":
                wps = await asyncio.to_thread(node.download_mission)
                for wp in wps: wp['lat'], wp['lon'] = EvilTransform.wgs2gcj(wp['lat'], wp['lon'])
                await websocket.send_json({"type": "mission_downloaded", "drone_id": d_id, "waypoints": wps})
            
            elif cmd == "GIMBAL_DIR": node.send_gimbal_cmd(msg.get("val"))
            elif cmd == "GIMBAL_ZOOM": node.send_gimbal_cmd("zoom", msg.get("val"))
            elif cmd == "GIMBAL_SET": node.send_gimbal_cmd("set_angle", msg.get("yaw"), msg.get("pitch"))
                
    except WebSocketDisconnect:
        task.cancel()

# ==========================================
# 4. 前端 HTML + JS
# ==========================================
def generate_html():
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Multi-Drone Web GCS 3D</title>
        <meta charset="utf-8">
        <script type="text/javascript"> window._AMapSecurityConfig = {{ securityJsCode: '3b542abbb6dde06fb6d0a6692089a30f' }}; </script>
        <script src="https://webapi.amap.com/maps?v=2.0&key=df08b9775f1b5949a902daf1696e6560&plugin=AMap.ControlBar"></script>
        <style>
            :root {{ --bg: #1e272e; --panel: #2f3640; --text: #d2dae2; --accent: #0984e3; --red: #d63031; --green: #00b894; }}
            body {{ margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); display: flex; height: 100vh; overflow: hidden; }}
            
            #sidebar {{ width: 220px; background: #2c3e50; display: flex; flex-direction: column; overflow-y: auto; z-index: 100; }}
            .drone-tab {{ padding: 20px; border-bottom: 1px solid #34495e; cursor: pointer; font-weight: bold; font-size: 16px; transition: 0.2s; }}
            .drone-tab:hover {{ background: #34495e; }}
            .drone-tab.active {{ background: var(--accent); color: white; border-left: 4px solid #fff; }}
            
            #main-area {{ flex: 1; display: flex; flex-direction: column; padding: 10px; gap: 0; overflow-y: auto; position: relative; }}
            
            .topbar {{ background: #ecf0f1; color: #2c3e50; padding: 10px 20px; border-radius: 6px; display: flex; align-items: center; justify-content: space-between; font-weight: bold; margin-bottom: 10px; }}
            .status-badge {{ padding: 5px 15px; border-radius: 4px; color: white; }}
            .badge-red {{ background: var(--red); }} .badge-green {{ background: var(--green); }} .badge-gray {{ background: #7f8c8d; }}
            
            .split-view {{ display: flex; flex: 1; gap: 5px; min-height: 200px; }}
            .video-container, .map-container {{ background: var(--panel); border-radius: 6px; display: flex; flex-direction: column; position: relative; }}
            
            .resizer {{ width: 8px; background: #34495e; cursor: col-resize; border-radius: 4px; transition: background 0.2s; z-index: 50; }}
            .resizer:hover, .resizer.dragging {{ background: var(--accent); }}

            .h-resizer {{ height: 12px; background: #34495e; cursor: row-resize; border-radius: 4px; transition: background 0.2s; z-index: 50; margin: 10px 0; display: flex; justify-content: center; align-items: center; }}
            .h-resizer::before {{ content: "•••••"; color: #7f8c8d; font-size: 14px; letter-spacing: 2px; }}
            .h-resizer:hover, .h-resizer.dragging {{ background: var(--accent); }}

            .panel-header {{ background: #34495e; padding: 8px 12px; font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; display:flex; justify-content: space-between; }}
            #video_player {{ flex: 1; width: 100%; background: #000; object-fit: contain; }}
            #map {{ flex: 1; width: 100%; min-height: 200px; position: relative; }}
            
            .map-zoom-btn {{ width: 36px; height: 36px; background: rgba(44,62,80,0.85); color: white; border: 1px solid #7f8c8d; border-radius: 4px; font-size: 24px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.2s; user-select: none; }}
            .map-zoom-btn:hover {{ background: var(--accent); }}

            .dashboard {{ background: #000; padding: 10px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; text-align: left; }}
            .dash-item {{ font-size: 11px; color: #aaa; }}
            .dash-val {{ font-size: 20px; font-weight: bold; display: block; margin-top:2px; }}
            .c-alt {{ color: #E0B0FF; }} .c-spd {{ color: #F39C12; }} .c-bat {{ color: #FF69B4; }} .c-hdg {{ color: #2ECC71; }}
            
            .bottom-controls {{ display: flex; gap: 10px; height: 300px; flex: none; }}
            .ctrl-box {{ background: var(--panel); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; flex: 1; overflow-y: auto; }}
            
            button {{ background: #487eb0; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; margin: 2px; }}
            button:hover {{ filter: brightness(1.2); }}
            input {{ padding: 6px; border-radius: 4px; border: 1px solid #7f8c8d; background: #353b48; color: white; width: 60px; }}
            
            table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            th, td {{ border: 1px solid #7f8c8d; padding: 5px; text-align: center; }}
            .selected-row {{ background: #34495e; }}
            
            .gimbal-pad {{ display: grid; grid-template-columns: 35px 35px 35px; gap: 4px; margin: 10px 0; }}
            .gimbal-pad button {{ width: 35px; height: 35px; padding: 0; background: #34495e; border: 1px solid #7f8c8d; }}
            .gimbal-pad button:hover {{ background: var(--green); }}
            
            #ctx-menu {{ display: none; position: absolute; background: #2f3640; border: 1px solid #7f8c8d; border-radius: 4px; padding: 10px; z-index: 9999; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }}
            .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 10000; justify-content: center; align-items: center; }}
            .modal-box {{ background: #2f3640; padding: 25px; border-radius: 8px; border: 1px solid #7f8c8d; width: 350px; display: flex; flex-direction: column; gap: 15px; }}
            .modal-box label {{ display: flex; justify-content: space-between; align-items: center; font-size: 14px; }}
            .modal-box input {{ width: 200px; }}
        </style>
    </head>
    <body>

        <div id="toast-container" style="position: fixed; top: 70px; left: 50%; transform: translateX(-50%); z-index: 10005; display: flex; flex-direction: column; align-items: center; pointer-events: none;"></div>

        <div id="sidebar">
            <div style="padding: 15px; text-align: center; border-bottom: 1px solid #34495e;">
                <button onclick="document.getElementById('add-modal').style.display='flex'" style="background:var(--green); width: 100%; font-size: 15px; padding: 10px;">➕ 添加无人机</button>
            </div>
            <div id="drone-tabs"></div>
            
            <div style="padding: 15px; border-top: 1px solid #34495e; margin-top: auto;">
                <div style="margin-bottom: 10px; font-size: 13px; border-bottom: 1px dashed #7f8c8d; padding-bottom: 10px;">
                    <div style="margin-bottom: 5px; color: #f39c12; font-weight: bold;">🛡️ 安全预警阈值</div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                        <span>低压报警 (V):</span>
                        <input type="text" id="in_batt_th" value="28.0" style="width: 40px; padding: 2px; text-align: center;">
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>丢包报警 (%):</span>
                        <input type="text" id="in_loss_th" value="10.0" style="width: 40px; padding: 2px; text-align: center;">
                    </div>
                </div>

                <label style="font-size: 13px; display: flex; align-items: center; gap: 5px; margin-bottom: 10px; color: #f39c12;">
                    <input type="checkbox" id="chk_offline_map" onchange="toggleOfflineMap()"> 
                    🌍 使用本地离线地图
                </label>
                
                <label style="font-size: 13px; display: flex; align-items: center; gap: 5px;">
                    <input type="checkbox" id="chk_debug" onchange="document.getElementById('debug_log').style.display = this.checked ? 'block' : 'none'"> 
                    开启指令调试/心跳日志
                </label>
                <textarea id="debug_log" readonly style="width: 100%; height: 150px; margin-top: 10px; display: none; background: #000; color: #0f0; border: 1px solid #7f8c8d; font-size: 11px; box-sizing: border-box;"></textarea>
            </div>
        </div>

        <div id="main-area">
            
            <div class="topbar">
                <div style="display: flex; align-items: center;">
                    <span id="ui_drone_name" style="font-size: 18px;">请先添加并选择一台无人机</span>
                    <button id="btn_remove_drone" onclick="removeCurrentDrone()" style="display:none; background: var(--red); padding: 4px 8px; margin-left: 15px; font-size: 12px; border-radius: 4px; cursor: pointer; color: white; border: none; font-weight: bold;">🗑️ 断开并移除</button>
                </div>
                <div style="display: flex; gap: 15px; align-items: center;">
                    <span>Link: <span id="ui_conn" class="status-badge badge-gray">N/A</span></span>
                    <span>Mode: <span id="ui_mode" style="color: #2c3e50;">N/A</span></span>
                    <span>Status: <span id="ui_arm" class="status-badge badge-gray">N/A</span></span>
                </div>
            </div>

            <div class="split-view" id="main-split-view">
                <div class="video-container" id="video-panel" style="flex: 0 0 40%;">
                    <div class="panel-header">📹 实时视频</div>
                    <video id="video_player" autoplay muted playsinline></video>
                </div>
                
                <div class="resizer" id="split-resizer" title="左右拖动调整视频/地图比例"></div>
                
                <div class="map-container" id="map-panel" style="flex: 1 1 0%;">
                    <div class="panel-header">
                        <span>🗺️ 3D飞行地图</span>
                    </div>
                    <div id="map"></div>
                    <div style="position: absolute; right: 15px; top: 120px; z-index: 160; display: flex; flex-direction: column; gap: 8px;">
                        <div class="map-zoom-btn" onclick="map.zoomIn()" title="放大地图">＋</div>
                        <div class="map-zoom-btn" onclick="map.zoomOut()" title="缩小地图">－</div>
                    </div>
                    
                    <div class="dashboard">
                        <div class="dash-item">Altitude(m)<span id="d_alt" class="dash-val c-alt">0.0</span></div>
                        <div class="dash-item">Speed(m/s)<span id="d_spd" class="dash-val c-spd">0.0</span></div>
                        <div class="dash-item">Battery(V)<span id="d_bat" class="dash-val c-bat">0.0</span></div>
                        <div class="dash-item">Dist(m)<span id="d_dst" class="dash-val" style="color:#FA8072;">0</span></div>
                        
                        <div class="dash-item">Heading(°)<span id="d_hdg" class="dash-val c-hdg">0</span></div>
                        <div class="dash-item">Ping<span id="d_ping" class="dash-val" style="color:#00BFFF;">--</span></div>
                        <div class="dash-item">Link Loss<span id="d_loss" class="dash-val" style="color:#ff9f43;">0.0%</span></div>
                        <div class="dash-item">GPS Status<span id="d_gps" class="dash-val" style="color:gray; font-size:14px; padding-top:5px;">N/A</span></div>
                    </div>
                </div>
            </div>

            <div class="h-resizer" id="h-resizer" title="上下拖动调整底部面板高度"></div>

            <div class="bottom-controls" id="bottom-controls">
                
                <div class="ctrl-box" style="flex: 0.8;">
                    <h3>Link & Video</h3>
                    <div style="margin-bottom: 10px;">
                        WHEP 视频流地址:<br>
                        <input type="text" id="in_whep" style="width: 90%; margin: 5px 0;">
                        <button onclick="startVideo()" style="background:var(--green)">播放</button>
                        <button onclick="stopVideo()" style="background:var(--red)">停止</button>
                    </div>
                </div>

                <div class="ctrl-box" style="flex: 1.2;">
                    <h3>Mission Planning</h3>
                    <div style="display:flex; gap: 5px; margin-bottom: 5px; flex-wrap: wrap;">
                        <button onclick="initMission()">Init</button>
                        <button onclick="moveRow(-1)">▲</button>
                        <button onclick="moveRow(1)">▼</button>
                        <button onclick="deleteRow()">Del</button>
                        <button onclick="clearMission()">Clr</button>
                        <button onclick="exportJSON()" style="background:#f39c12">Export</button>
                        <button onclick="document.getElementById('import_file').click()" style="background:#d35400">Import</button>
                        <input type="file" id="import_file" accept=".json" style="display:none" onchange="importJSON(event)">
                        
                        <button onclick="uploadMission()" style="background:#8e44ad">Upload</button>
                        <button onclick="downloadMission()" style="background:#2980b9">Download</button>
                    </div>
                    <div style="flex:1; overflow-y:auto;">
                        <table id="msn_table">
                            <tr><th>Cmd</th><th>Lat</th><th>Lon</th><th>Alt</th></tr>
                        </table>
                    </div>
                </div>

                <div class="ctrl-box" style="flex: 1.4;">
                    <h3>Control & Gimbal</h3>
                    <div style="display:flex; gap: 5px; flex-wrap: wrap;">
                        <button style="background:#95a5a6" onclick="cmd('MODE','STABILIZE')">STAB</button>
                        <button style="background:#3498db" onclick="cmd('MODE','ALT_HOLD')">ALT_HOLD</button>
                        <button style="background:#9b59b6" onclick="cmd('MODE','LOITER')">LOITER</button>
                        <button style="background:#1abc9c" onclick="cmd('MODE','GUIDED')">GUIDED</button>
                        <button style="background:#f1c40f; color:black" onclick="cmd('MODE','RTL')">RTL</button>
                        <button style="background:#e67e22" onclick="cmd('MODE','LAND')">LAND</button>
                    </div>
                    <div style="margin-top: 10px; display:flex; gap:5px; align-items: center;">
                        <button style="background:var(--red)" onclick="cmd('ARM')">ARM</button>
                        <button style="background:#e67e22; color:black; font-weight:bold; border: 1px solid #d35400;" onclick="forceArm()" title="跳过自检强制解锁">⚠️ FORCE ARM</button>
                        
                        <button onclick="cmd('DISARM')">DISARM</button>
                        <span style="margin-left: 10px;">Alt(m):</span>
                        <input type="text" id="in_alt" value="10.0">
                        <button style="font-weight:bold" onclick="cmd('TAKEOFF', document.getElementById('in_alt').value)">Takeoff</button>
                        <button style="background:#2980b9; margin-left: 10px;" onclick="if(current_lat!==0) map.panTo([current_lon, current_lat])">📍 找飞机</button>
                    </div>
                    
                    <div style="margin-top: 10px; display:flex; gap:5px; align-items: center;">
                        <button onclick="cmd('START_MISSION')" style="background:#c0392b; font-weight:bold; margin-right: 15px;">🚀 Start Mission</button>
                        <button onclick="cmd('PAUSE')" style="background:#f39c12; font-weight:bold; color:black;">⏸ 暂停(悬停)</button>
                        <button onclick="cmd('RESUME')" style="background:#2ecc71; font-weight:bold; color:black;">▶️ 恢复飞行</button>
                    </div>
                    
                    <hr style="border-color:#7f8c8d; width:100%; margin: 10px 0;">
                    
                    <div style="display:flex; justify-content: space-between;">
                        <div>
                            <div>机头微调</div>
                            <button onclick="cmd('YAW', -10)">⏪ 左转10°</button>
                            <button onclick="cmd('YAW', 10)">⏩ 右转10°</button>
                            <div style="margin-top:5px;">
                                <input type="text" id="in_yaw_abs" placeholder="0-360" style="width:40px;">
                                <button style="background:#8e44ad" onclick="cmd('YAW_ABS', document.getElementById('in_yaw_abs').value)">转至</button>
                            </div>
                            
                            <div style="margin-top: 15px; border-top: 1px dashed #7f8c8d; padding-top: 10px;">
                                <div>相对飞行 (米): <input type="text" id="in_move_dist" value="5" style="width:30px;"></div>
                                <div style="display: grid; grid-template-columns: 40px 40px 40px; gap: 4px; margin-top: 5px; text-align:center;">
                                    <div></div>
                                    <button style="background:#3498db;" onclick="moveRel(1, 0)">前</button>
                                    <div></div>
                                    <button style="background:#3498db;" onclick="moveRel(0, -1)">左</button>
                                    <div></div>
                                    <button style="background:#3498db;" onclick="moveRel(0, 1)">右</button>
                                    <div></div>
                                    <button style="background:#3498db;" onclick="moveRel(-1, 0)">后</button>
                                    <div></div>
                                </div>
                            </div>
                        </div>
                        
                        <div>
                            <div>云台反馈: Y <span id="d_gy">0</span> | P <span id="d_gp">0</span></div>
                            <div style="display:flex; gap:10px;">
                                <div class="gimbal-pad">
                                    <div></div><button onmousedown="gcmd('up')" onmouseup="gcmd('stop')">▲</button><div></div>
                                    <button onmousedown="gcmd('left')" onmouseup="gcmd('stop')">◀</button>
                                    <button onclick="gcmd('center')">●</button>
                                    <button onmousedown="gcmd('right')" onmouseup="gcmd('stop')">▶</button>
                                    <div></div><button onmousedown="gcmd('down')" onmouseup="gcmd('stop')">▼</button><div></div>
                                </div>
                                <div style="display:flex; flex-direction:column; justify-content:center; gap:5px;">
                                    <button onmousedown="gcmd('zoom',1)" onmouseup="gcmd('zoom',0)">🔍 +</button>
                                    <button onmousedown="gcmd('zoom',-1)" onmouseup="gcmd('zoom',0)">🔍 -</button>
                                    <input type="text" id="in_gy" placeholder="Yaw" style="width:40px; padding:2px;">
                                    <input type="text" id="in_gp" placeholder="Pit" style="width:40px; padding:2px;">
                                    <button style="background:#d35400" onclick="gcmd('set_angle', document.getElementById('in_gy').value, document.getElementById('in_gp').value)">SET</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="ctrl-box" style="flex: 1.2;">
                    <h3>多机协同待命区</h3>
                    
                    <div style="display:flex; gap: 10px; margin-bottom: 5px;">
                        <label style="color:#f39c12; font-weight:bold; cursor:pointer;">
                            <input type="checkbox" id="chk_staging_mode" onchange="renderStagingArea()"> 启用待命拦截模式
                        </label>
                    </div>

                    <div style="background: #1e272e; padding: 8px; border-radius: 4px; border: 1px solid #e74c3c; margin-bottom: 5px;">
                        <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                            <label style="color:#e74c3c; font-weight:bold; cursor:pointer;">
                                <input type="checkbox" id="chk_anti_collision" onchange="toggleAntiCollision()"> 🛡️ 开启避让防撞
                            </label>
                            <span style="font-size: 13px; color:#d2dae2;">半径: 
                                <input type="number" id="in_collision_radius" value="5.0" step="0.5" style="width: 45px; padding: 2px; text-align:center;" onchange="toggleAntiCollision()"> 米
                            </span>
                        </div>
                        <div style="font-size: 13px; color: #aaa; text-align: center; border-top: 1px dashed #7f8c8d; padding-top: 5px;">
                            两机实时水平距离: <span id="ui_swarm_dist" style="color:#00BFFF; font-weight:bold; font-size:16px;">等待定位...</span>
                        </div>
                    </div>
                    
                    <div id="staging_list" style="flex:1; overflow-y:auto; background:#1e272e; margin:5px 0; padding:8px; border:1px solid #7f8c8d; font-size:12px; border-radius:4px;">
                        <div style="color:gray;">暂无待命指令...</div>
                    </div>
                    <div style="display:flex; gap:5px;">
                        <button onclick="clearStaging()" style="background:#7f8c8d; flex:1;">清空</button>
                        <button onclick="showStagingModal()" style="background:#8e44ad; flex:2; font-weight:bold; font-size:14px;">🛸 批量多机控制</button>
                    </div>
                </div>

            </div>
        </div>

        <div id="ctx-menu">
            <h4>✈️ GUIDED 飞行至此</h4>
            <label>速度(m/s): <input type="text" id="ctx_spd" value="5.0" style="width:60px"></label><br><br>
            <label>高度(m): <input type="text" id="ctx_alt" value="30.0" style="width:60px"></label><br><br>
            <label>朝向(度): <input type="text" id="ctx_yaw" value="0" style="width:60px"></label><br><br>
            <button onclick="executeGuidedFly()" style="background:var(--green)">执行飞行</button>
            <button onclick="closeCtxMenu()">取消</button>
        </div>

        <div id="add-modal" class="modal-overlay">
            <div class="modal-box">
                <h3 style="margin-top:0;">📡 配置并连接无人机</h3>
                <label>无人机名称: <input type="text" id="m_name" value="新设备 01"></label>
                
                <div style="display: flex; flex-direction: column; gap: 5px;">
                    <div style="font-size: 14px; display: flex; justify-content: space-between;">
                        <span>FCU 地址 (IP 或 串口):</span>
                        <input type="text" id="m_fcu" value="udpout:10.252.1.11:14550" title="例如: udpout:IP:14550 或 tcp:127.0.0.1:5760">
                    </div>
                    <div style="font-size: 13px; color: #aaa; text-align: right;">(支持 udp/tcp 或 COM3, /dev/ttyUSB0)</div>
                </div>

                <label>波特率 (仅串口数传): 
                    <select id="m_baud" style="width: 200px; padding: 6px; border-radius: 4px; border: 1px solid #7f8c8d; background: #353b48; color: white;">
                        <option value="57600" selected>57600 (默认)</option>
                        <option value="115200">115200</option>
                        <option value="921600">921600</option>
                        <option value="1500000">1500000</option>
                    </select>
                </label>

                <label>MQTT 控制 IP: <input type="text" id="m_mqtt" value="10.252.1.11"></label>
                <label>WHEP 视频流地址: <input type="text" id="m_whep" value="http://10.252.1.11:8889/main.264/whep"></label>
                
                <div style="display:flex; justify-content: flex-end; gap: 10px; margin-top: 10px;">
                    <button onclick="document.getElementById('add-modal').style.display='none'" style="background: #7f8c8d;">取消</button>
                    <button onclick="submitNewDrone()" style="background: var(--green);">确认并连接</button>
                </div>
            </div>
        </div>

        <div id="warning-modal" class="modal-overlay" style="z-index: 10001; display: none;">
            <div class="modal-box" style="border: 2px solid #e74c3c; text-align: center; width: 400px;">
                <h2 style="color: #e74c3c; margin-top: 0;">⚠️ 飞行安全警告</h2>
                <p id="warning-text" style="font-size: 16px; margin: 20px 0; color: #ecf0f1; line-height: 1.5;"></p>
                <div style="display:flex; justify-content: center; gap: 15px;">
                    <button onclick="document.getElementById('warning-modal').style.display='none'" style="background: #7f8c8d; padding: 10px 20px; font-size: 14px;">我知道了 (忽略 60s)</button>
                    <button onclick="sendControlCmd({{drone_id: current_id, command: 'MODE', val: 'RTL'}}); document.getElementById('warning-modal').style.display='none'" style="background: #e74c3c; padding: 10px 20px; font-weight: bold; font-size: 14px;">一键返航 (RTL)</button>
                </div>
            </div>
        </div>

        <div id="staging-modal" class="modal-overlay" style="z-index: 10002; display: none;">
            <div class="modal-box" style="border: 2px solid #8e44ad; width: 450px;">
                <h3 style="color: #8e44ad; margin-top: 0;">🛸 批量执行确认</h3>
                <p style="font-size:13px; color:#aaa; margin-top:0;">以下指令即将发送给对应的无人机，请仔细核对：</p>
                <div id="staging-confirm-text" style="font-size: 14px; margin: 15px 0; color: #ecf0f1; max-height: 250px; overflow-y: auto; background: #1e272e; padding: 10px; border-radius: 4px;"></div>
                <div style="display:flex; justify-content: flex-end; gap: 10px;">
                    <button onclick="document.getElementById('staging-modal').style.display='none'" style="background: #7f8c8d; padding: 8px 15px;">取消</button>
                    <button onclick="confirmExecuteStaged()" style="background: var(--green); padding: 8px 15px; font-weight: bold;">确认发送</button>
                </div>
            </div>
        </div>

        <script>
            let current_id = null;
            let current_lat = 0, current_lon = 0;
            let knownDrones = {{}}; 
            let lastWarningTime = 0; 
            let stagedCommands = [];
            
            const ws = new WebSocket("ws://" + location.host + "/ws");
            
            function ws_send(payload) {{
                if (document.getElementById('chk_debug').checked) {{
                    const logBox = document.getElementById('debug_log');
                    const time = new Date().toLocaleTimeString();
                    logBox.value = "[" + time + "] 发送: " + JSON.stringify(payload) + "\\n" + logBox.value;
                }}
                ws.send(JSON.stringify(payload));
            }}

            // 【新增 JS】：动态展示飞控报错文本的浮窗
            function showToast(msg) {{
                const container = document.getElementById('toast-container');
                const toast = document.createElement('div');
                toast.style.cssText = "background: rgba(231, 76, 60, 0.9); color: white; padding: 12px 24px; border-radius: 6px; margin-bottom: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); font-size: 14px; font-weight: bold; pointer-events: auto; transition: opacity 0.5s;";
                toast.innerHTML = "🚨 " + msg;
                container.appendChild(toast);
                
                // 5秒后自动消失
                setTimeout(() => {{ 
                    toast.style.opacity = '0'; 
                    setTimeout(() => toast.remove(), 500); 
                }}, 5000);
            }}

            function toggleAntiCollision() {{
                const isEnabled = document.getElementById('chk_anti_collision').checked;
                let radius = parseFloat(document.getElementById('in_collision_radius').value);
                if(isNaN(radius) || radius <= 0) radius = 5.0; 
                ws_send({{ command: "TOGGLE_ANTI_COLLISION", enabled: isEnabled, radius: radius }});
            }}

            function sendControlCmd(payload) {{
                const isStaging = document.getElementById('chk_staging_mode').checked;
                if (isStaging) {{
                    stagedCommands.push(payload);
                    renderStagingArea();
                }} else {{
                    ws_send(payload);
                }}
            }}

            function removeCurrentDrone() {{
                if (!current_id) return;
                const dName = knownDrones[current_id] ? knownDrones[current_id].name : current_id;
                if (!confirm(`确定要断开并移除 [${{dName}}] 吗？\\n注意：这不会关闭后台的仿真器，只会断开网页地面站与它的连接。`)) return;
                
                ws_send({{ command: "REMOVE_DRONE", drone_id: current_id }});
                
                const tab = document.getElementById('tab-' + current_id);
                if (tab) tab.remove();
                
                if (typeof map !== 'undefined' && map) {{
                    if (droneMarkers[current_id]) {{ map.remove(droneMarkers[current_id]); delete droneMarkers[current_id]; }}
                    if (ghostMarkers[current_id]) {{ map.remove(ghostMarkers[current_id]); delete ghostMarkers[current_id]; }}
                    if (predictLines[current_id]) {{ map.remove(predictLines[current_id]); delete predictLines[current_id]; }}
                    if (tracePolylines[current_id]) {{ map.remove(tracePolylines[current_id]); delete tracePolylines[current_id]; }}
                }}
                delete flightTraces[current_id];
                delete knownDrones[current_id];
                
                const remainingIds = Object.keys(knownDrones);
                if (remainingIds.length > 0) {{
                    switchDrone(remainingIds[0]);
                }} else {{
                    current_id = null;
                    document.getElementById('ui_drone_name').innerText = "请先添加并选择一台无人机";
                    document.getElementById('btn_remove_drone').style.display = 'none';
                    document.getElementById('ui_conn').innerText = "N/A";
                    document.getElementById('ui_conn').className = 'status-badge badge-gray';
                    document.getElementById('ui_mode').innerText = "N/A";
                    document.getElementById('ui_arm').innerText = "N/A";
                    document.getElementById('ui_arm').className = 'status-badge badge-gray';
                    
                    document.getElementById('d_alt').innerText = "0.0";
                    document.getElementById('d_spd').innerText = "0.0";
                    document.getElementById('d_bat').innerText = "0.0";
                    document.getElementById('d_dst').innerText = "0";
                    document.getElementById('d_hdg').innerText = "0";
                    document.getElementById('d_ping').innerText = "--";
                    document.getElementById('d_loss').innerText = "0.0%";
                    document.getElementById('d_gps').innerText = "N/A";
                    document.getElementById('d_gy').innerText = "0";
                    document.getElementById('d_gp').innerText = "0";
                    
                    stopVideo();
                }}
            }}

            function getCommandExplanation(p) {{
                const dName = knownDrones[p.drone_id] ? knownDrones[p.drone_id].name : p.drone_id;
                let act = p.command;
                if(p.command === "MODE") act = `切换模式为 <b style="color:#f1c40f">${{p.val}}</b>`;
                if(p.command === "ARM") act = `<b style="color:#e74c3c">解锁电机 (ARM)</b>`;
                if(p.command === "FORCE_ARM") act = `<b style="color:#e67e22">强制解锁电机 (FORCE ARM)</b>`;
                if(p.command === "DISARM") act = `锁定电机 (DISARM)`;
                if(p.command === "TAKEOFF") act = `起飞至 <b style="color:#3498db">${{p.val}} 米</b>`;
                if(p.command === "START_MISSION") act = `<b style="color:#2ecc71">开始执行航线任务</b>`;
                if(p.command === "PAUSE") act = `<b style="color:#f39c12">暂停飞行并悬停 (GUIDED_HOVER)</b>`;
                if(p.command === "RESUME") act = `<b style="color:#2ecc71">恢复之前的飞行 (AUTO/GUIDED)</b>`;
                if(p.command === "YAW") act = `机头偏转 ${{p.val}} 度`;
                if(p.command === "YAW_ABS") act = `机头转向 ${{p.val}} 度`;
                if(p.command === "MOVE_RELATIVE") act = `相对移动 - 前:${{p.dx}}m 右:${{p.dy}}m 下:${{p.dz}}m`;
                if(p.command === "GUIDED_FLY") act = `飞往目标坐标 (Alt:${{p.alt}}m, Spd:${{p.speed}}m/s)`;
                if(p.command === "GIMBAL_DIR" || p.command === "GIMBAL_ZOOM" || p.command === "GIMBAL_SET") act = `云台控制 (${{p.val || 'SET'}})`;
                
                return `<span style="color:#3498db">[${{dName}}]</span> 将执行: ${{act}}`;
            }}

            function renderStagingArea() {{
                const list = document.getElementById('staging_list');
                if(!list) return;
                if(stagedCommands.length === 0) {{
                    list.innerHTML = '<div style="color:gray;">暂无待命指令...</div>';
                    return;
                }}
                list.innerHTML = stagedCommands.map((p, i) => {{
                    return `<div style="border-bottom:1px dashed #34495e; padding:5px 0;">${{i+1}}. ${{getCommandExplanation(p)}}</div>`;
                }}).join('');
            }}

            function clearStaging() {{
                stagedCommands = [];
                renderStagingArea();
            }}

            function showStagingModal() {{
                if(stagedCommands.length === 0) return alert("待命区为空，请先下发指令！");
                
                let htmlMsg = "<ul style='padding-left: 20px; margin: 0;'>";
                stagedCommands.forEach(p => {{
                    htmlMsg += `<li style="margin-bottom: 8px;">${{getCommandExplanation(p)}}</li>`;
                }});
                htmlMsg += "</ul>";
                
                document.getElementById('staging-confirm-text').innerHTML = htmlMsg;
                document.getElementById('staging-modal').style.display = 'flex';
            }}

            function confirmExecuteStaged() {{
                stagedCommands.forEach(p => {{
                    ws_send(p); 
                }});
                document.getElementById('staging-modal').style.display = 'none';
                clearStaging(); 
            }}

            function addSidebarTab(id, name) {{
                const container = document.getElementById('drone-tabs');
                const div = document.createElement('div');
                div.id = 'tab-' + id;
                div.className = 'drone-tab' + (id === current_id ? ' active' : '');
                div.innerText = name;
                div.onclick = () => switchDrone(id, div);
                container.appendChild(div);
            }}

            function switchDrone(id, el) {{
                current_id = id;
                document.querySelectorAll('.drone-tab').forEach(t => t.classList.remove('active'));
                if (el) el.classList.add('active');
                else {{
                    const t = document.getElementById('tab-' + id);
                    if(t) t.classList.add('active');
                }}
                
                const d_conf = knownDrones[id];
                if(d_conf) {{
                    document.getElementById('ui_drone_name').innerText = d_conf.name;
                    document.getElementById('btn_remove_drone').style.display = 'inline-block'; 
                    document.getElementById('in_whep').value = d_conf.rtsp_url;
                }}
                stopVideo();
            }}

            function submitNewDrone() {{
                const ws_ready = ws && ws.readyState === WebSocket.OPEN;
                if (!ws_ready) return alert("WebSocket 未连接，请稍后再试！");

                ws_send({{
                    command: "ADD_DRONE",
                    name: document.getElementById('m_name').value,
                    fcu_url: document.getElementById('m_fcu').value,
                    baudrate: parseInt(document.getElementById('m_baud').value),
                    mqtt_ip: document.getElementById('m_mqtt').value,
                    rtsp_url: document.getElementById('m_whep').value
                }});
                document.getElementById('add-modal').style.display = 'none';
            }}

            let map;
            let droneMarkers = {{}}; 
            let ghostMarkers = {{}}; 
            let predictLines = {{}}; 
            let flightTraces = {{}}; 
            let tracePolylines = {{}};
            let wpMarkers = [];
            let ctx_target = null; 
            
            let onlineLayer, offlineLayer;
            let hasCenteredMap = false;

            try {{
                onlineLayer = new AMap.TileLayer.Satellite();
                
                offlineLayer = new AMap.TileLayer({{
                    getTileUrl: 'http://' + location.host + '/tiles/[z]/[x]/[y].png',
                    zIndex: 99,
                    zooms: [3, 20],
                    opacity: 1,
                    visible: false 
                }});

                map = new AMap.Map('map', {{ 
                    resizeEnable: true,
                    viewMode: '3D', pitch: 0, rotation: 0, zoom: 16, center: [114.53, 22.54], 
                    features: ['bg', 'road', 'point'], 
                    layers: [
                        onlineLayer,
                        offlineLayer, 
                        new AMap.Buildings({{ zooms: [16, 20], zIndex: 100, heightFactor: 1.5 }})
                    ] 
                }});

                map.addControl(new AMap.ControlBar({{ position: {{ right: '10px', top: '10px' }} }}));

                let isDraggingMap = false;
                map.on('dragstart', () => isDraggingMap = true);
                map.on('dragend', () => setTimeout(() => isDraggingMap = false, 150));

                function closeCtxMenu() {{ document.getElementById('ctx-menu').style.display = 'none'; }}

                map.on('rightclick', function(e) {{
                    if (isDraggingMap) return; 
                    ctx_target = {{ lat: e.lnglat.getLat(), lon: e.lnglat.getLng() }};
                    const menu = document.getElementById('ctx-menu');
                    menu.style.display = 'block';
                    menu.style.left = e.pixel.x + 230 + 'px'; 
                    menu.style.top = e.pixel.y + 60 + 'px';
                }});

                map.on('click', function(e) {{
                    closeCtxMenu();
                    addWpRow('WAYPOINT', e.lnglat.getLat(), e.lnglat.getLng(), 30.0);
                }});

                const splitResizer = document.getElementById('split-resizer');
                const videoPanel = document.getElementById('video-panel');
                const mainSplitView = document.getElementById('main-split-view');
                let isDraggingSplitter = false;

                splitResizer.addEventListener('mousedown', function(e) {{
                    isDraggingSplitter = true;
                    splitResizer.classList.add('dragging');
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                }});

                document.addEventListener('mousemove', function(e) {{
                    if (!isDraggingSplitter) return;
                    const containerRect = mainSplitView.getBoundingClientRect();
                    let newWidthPercent = ((e.clientX - containerRect.left) / containerRect.width) * 100;
                    if (newWidthPercent < 20) newWidthPercent = 20;
                    if (newWidthPercent > 80) newWidthPercent = 80;
                    videoPanel.style.flex = `0 0 ${{newWidthPercent}}%`;
                }});

                document.addEventListener('mouseup', function(e) {{
                    if (isDraggingSplitter) {{
                        isDraggingSplitter = false;
                        splitResizer.classList.remove('dragging');
                        document.body.style.cursor = 'default';
                        document.body.style.userSelect = 'auto';
                        if(map) map.resize(); 
                    }}
                }});

                const hResizer = document.getElementById('h-resizer');
                const bottomControls = document.getElementById('bottom-controls');
                const mainArea = document.getElementById('main-area');
                let isDraggingH = false;

                hResizer.addEventListener('mousedown', function(e) {{
                    isDraggingH = true;
                    hResizer.classList.add('dragging');
                    document.body.style.cursor = 'row-resize';
                    document.body.style.userSelect = 'none';
                }});

                document.addEventListener('mousemove', function(e) {{
                    if (!isDraggingH) return;
                    const containerRect = mainArea.getBoundingClientRect();
                    let newBottomHeight = containerRect.bottom - e.clientY - 15;
                    
                    if (newBottomHeight < 100) newBottomHeight = 100; 
                    if (newBottomHeight > containerRect.height - 200) newBottomHeight = containerRect.height - 200; 
                    
                    bottomControls.style.height = `${{newBottomHeight}}px`;
                }});

                document.addEventListener('mouseup', function(e) {{
                    if (isDraggingH) {{
                        isDraggingH = false;
                        hResizer.classList.remove('dragging');
                        document.body.style.cursor = 'default';
                        document.body.style.userSelect = 'auto';
                        if(map) map.resize(); 
                    }}
                }});

            }} catch (err) {{
                console.error("地图加载失败:", err);
            }}

            function toggleOfflineMap() {{
                if (!map) return;
                const isOffline = document.getElementById('chk_offline_map').checked;
                
                if (isOffline) {{
                    onlineLayer.hide();
                    offlineLayer.show();
                    console.log("🌍 已切换至本地离线图层");
                }} else {{
                    offlineLayer.hide();
                    onlineLayer.show();
                    console.log("🌐 已切换至在线卫星图层");
                }}
                
                map.setZoom(map.getZoom());
            }}

            ws.onmessage = function(event) {{
                const msg = JSON.parse(event.data);
                
                if (msg.type === "telemetry") {{

                    const droneKeys = Object.keys(msg.data);
                    
                    if (droneKeys.length >= 2) {{
                        const d1 = msg.data[droneKeys[0]];
                        const d2 = msg.data[droneKeys[1]];
                        
                        if (d1.lat !== 0 && d2.lat !== 0) {{
                            const dist = getOfflineDistance(d1.lat, d1.lon, d2.lat, d2.lon);
                            const uiDist = document.getElementById('ui_swarm_dist');
                            uiDist.innerText = dist.toFixed(1) + " 米";
                            
                            const threshold = parseFloat(document.getElementById('in_collision_radius').value) || 5.0;
                            uiDist.style.color = dist < (threshold + 2.0) ? "#e74c3c" : "#00BFFF";
                        }}
                    }} else {{
                        document.getElementById('ui_swarm_dist').innerText = "等待第二台飞机...";
                        document.getElementById('ui_swarm_dist').style.color = "gray";
                    }}

                    for (const [did, data] of Object.entries(msg.data)) {{
                        
                        if (!knownDrones[did]) {{
                            knownDrones[did] = {{ name: data.name, rtsp_url: data.rtsp_url }};
                            addSidebarTab(did, data.name);
                            if (!current_id) switchDrone(did);
                        }}

                        // 【新增】：接收并显示飞控的报错弹窗文本
                        if (data.status_text) {{
                            showToast(`[${{knownDrones[did].name}}] ${{data.status_text}}`);
                            if (document.getElementById('chk_debug').checked) {{
                                const logBox = document.getElementById('debug_log');
                                logBox.value = `[${{new Date().toLocaleTimeString()}}] ⚠️ 飞控警告: ${{data.status_text}}\n` + logBox.value;
                            }}
                        }}
                        
                        if (knownDrones[did].last_yielding !== undefined) {{
                            if (!knownDrones[did].last_yielding && data.yielding) {{
                                if (document.getElementById('chk_debug').checked) {{
                                    const time = new Date().toLocaleTimeString();
                                    const logBox = document.getElementById('debug_log');
                                    logBox.value = `[${{time}}] 🛑 警告: ${{data.name}} 触发防撞，进入避让悬停！\n` + logBox.value;
                                }}
                            }} else if (knownDrones[did].last_yielding && !data.yielding) {{
                                if (document.getElementById('chk_debug').checked) {{
                                    const time = new Date().toLocaleTimeString();
                                    const logBox = document.getElementById('debug_log');
                                    logBox.value = `[${{time}}] ✅ 恢复: ${{data.name}} 安全间距达标或人工干预，恢复原任务！\n` + logBox.value;
                                }}
                            }}
                        }}
                        knownDrones[did].last_yielding = data.yielding; 

                        if (data.hb_log && document.getElementById('chk_debug').checked) {{
                            const logBox = document.getElementById('debug_log');
                            logBox.value = data.hb_log + "\\n" + logBox.value;
                        }}

                        if (did === current_id) {{
                            current_lat = data.lat; 
                            current_lon = data.lon; 
                            
                            document.getElementById('ui_conn').innerText = data.connected ? "CONNECTED" : "WAITING";
                            document.getElementById('ui_conn').className = 'status-badge ' + (data.connected ? 'badge-green' : 'badge-red');
                            
                            if (data.yielding) {{
                                document.getElementById('ui_mode').innerHTML = `${{data.mode}} <span style="background:#e74c3c; color:white; padding:2px 6px; border-radius:4px; font-size:12px; margin-left:5px;">避让悬停</span>`;
                            }} else {{
                                document.getElementById('ui_mode').innerText = data.mode;
                            }}
                            
                            document.getElementById('ui_arm').innerText = data.armed;
                            document.getElementById('ui_arm').className = 'status-badge ' + (data.armed === "ARMED" ? 'badge-red' : 'badge-gray');
                            
                            document.getElementById('d_alt').innerText = data.alt.toFixed(1);
                            document.getElementById('d_spd').innerText = data.spd.toFixed(1);
                            document.getElementById('d_bat').innerText = data.batt.toFixed(1);
                            document.getElementById('d_dst').innerText = data.dist_home.toFixed(0);
                            document.getElementById('d_hdg').innerText = data.heading.toFixed(0);
                            
                            document.getElementById('d_ping').innerText = (data.avg_ping_ms || 0).toFixed(0) + " ms";
                            document.getElementById('d_ping').style.color = (data.avg_ping_ms > 500) ? "#f39c12" : "#00BFFF";
                            
                            document.getElementById('d_loss').innerText = (data.hb_loss_rate || 0).toFixed(1) + "%";
                            
                            let gps_color = data.fix < 3 ? "red" : (data.fix === 6 ? "#00BFFF" : "#2ecc71");
                            const fixStr = {{0:"No Fix",1:"No Fix",2:"2D",3:"3D",4:"DGPS",5:"RTK Float",6:"RTK Fixed"}}[data.fix] || "Unknown";
                            document.getElementById('d_gps').innerText = `${{fixStr}}(${{data.sats}})`;
                            document.getElementById('d_gps').style.color = gps_color;

                            document.getElementById('d_gy').innerText = data.gimbal_yaw.toFixed(1);
                            document.getElementById('d_gp').innerText = data.gimbal_pitch.toFixed(1);

                            if (data.armed === "ARMED") {{
                                let warningMsgs = [];
                                let lossTh = parseFloat(document.getElementById('in_loss_th').value);
                                if (isNaN(lossTh)) lossTh = 10.0;
                                let battTh = parseFloat(document.getElementById('in_batt_th').value);
                                if (isNaN(battTh)) battTh = 28.0;

                                if (data.hb_loss_rate > lossTh) warningMsgs.push(`⚠️ 心跳丢包率: <b>${{data.hb_loss_rate.toFixed(1)}}%</b>`);
                                if (data.batt > 0 && data.batt < battTh) warningMsgs.push(`⚠️ 电池电压仅: <b>${{data.batt.toFixed(1)}}V</b>`);
                                
                                if (warningMsgs.length > 0) {{
                                    const now = Date.now();
                                    if (document.getElementById('warning-modal').style.display === 'none' && (now - lastWarningTime > 60000)) {{
                                        document.getElementById('warning-text').innerHTML = warningMsgs.join("<br><br>") + "<br><br><b>建议立即执行返航 (RTL)！</b>";
                                        document.getElementById('warning-modal').style.display = 'flex';
                                        lastWarningTime = now; 
                                    }}
                                }}
                            }}
                        }}

                        if (typeof AMap !== 'undefined' && map && data.lat !== 0) {{
                            let display_lat = data.lat !== 0 ? data.lat : 22.54;
                            let display_lon = data.lon !== 0 ? data.lon : 114.53;
                            
                            const color = did === current_id ? "#e74c3c" : "#3498db";
                            
                            let iconHtml = `<div style="transform: rotate(${{data.heading}}deg); transform-origin: center center; position:relative;">
                                <svg viewBox="0 0 100 100" width="45" height="45" xmlns="http://www.w3.org/2000/svg">
                                    <line x1="20" y1="20" x2="80" y2="80" stroke="${{color}}" stroke-width="6" stroke-linecap="round"/>
                                    <line x1="20" y1="80" x2="80" y2="20" stroke="${{color}}" stroke-width="6" stroke-linecap="round"/>
                                    <circle cx="20" cy="20" r="14" fill="rgba(0,0,0,0.6)" stroke="${{color}}" stroke-width="2"/>
                                    <circle cx="80" cy="80" r="14" fill="rgba(0,0,0,0.6)" stroke="${{color}}" stroke-width="2"/>
                                    <circle cx="20" cy="80" r="14" fill="rgba(0,0,0,0.6)" stroke="${{color}}" stroke-width="2"/>
                                    <circle cx="80" cy="20" r="14" fill="rgba(0,0,0,0.6)" stroke="${{color}}" stroke-width="2"/>
                                    <circle cx="50" cy="50" r="12" fill="${{color}}"/>
                                    <polygon points="50,5 35,30 65,30" fill="#f1c40f"/>
                                </svg>
                                <div style="background:rgba(0,0,0,0.8); color:#00ff00; border:1px solid ${{color}}; font-size:12px; padding:2px 5px; border-radius:4px; position:absolute; top:45px; left:-5px; white-space:nowrap; transform: rotate(-${{data.heading}}deg);">
                                    Alt: ${{data.alt.toFixed(1)}}m
                                </div>
                            </div>`;

                            if (!droneMarkers[did]) {{
                                droneMarkers[did] = new AMap.Marker({{
                                    position: [display_lon, display_lat],
                                    content: iconHtml,
                                    offset: new AMap.Pixel(-22.5, -22.5),
                                    anchor: 'center',
                                    zIndex: 150
                                }});
                                map.add(droneMarkers[did]);
                            }} else {{
                                droneMarkers[did].setPosition([display_lon, display_lat]);
                                droneMarkers[did].setContent(iconHtml);
                            }}

                            if (!flightTraces[did]) flightTraces[did] = [];
                            
                            let len = flightTraces[did].length;
                            if (len === 0 || getOfflineDistance(flightTraces[did][len-1][1], flightTraces[did][len-1][0], display_lat, display_lon) > 1.0) {{
                                flightTraces[did].push([display_lon, display_lat]);
                                
                                if (!tracePolylines[did]) {{
                                    tracePolylines[did] = new AMap.Polyline({{
                                        path: flightTraces[did], strokeColor: color, strokeWeight: 3, strokeOpacity: 0.6, zIndex: 120
                                    }});
                                    map.add(tracePolylines[did]);
                                }} else {{
                                    tracePolylines[did].setPath(flightTraces[did]);
                                }}
                            }}

                            let showGhost = false;
                            
                            if ((data.mode === "GUIDED" || data.mode === "AUTO") && data.target_lat !== 0 && data.target_lon !== 0 && !data.yielding) {{
                                
                                let distToFinalTarget = getOfflineDistance(display_lat, display_lon, data.target_lat, data.target_lon);
                                
                                if (distToFinalTarget > 1.0) {{
                                    showGhost = true;
                                    
                                    let v0 = data.spd;     
                                    let vmax = 5.0;         
                                    let amax = 2.5;         
                                    let t = 5.0;            
                                    
                                    let t_accel = Math.max(0, (vmax - v0) / amax);
                                    let d_pred = 0;
                                    
                                    if (t_accel >= t) {{
                                        d_pred = v0 * t + 0.5 * amax * t * t;
                                    }} else {{
                                        let d_accel = v0 * t_accel + 0.5 * amax * t_accel * t_accel;
                                        let d_cruise = vmax * (t - t_accel);
                                        d_pred = d_accel + d_cruise;
                                    }}
                                    
                                    if (d_pred > distToFinalTarget) {{
                                        d_pred = distToFinalTarget;
                                    }}
                                    
                                    let ratio = d_pred / distToFinalTarget;
                                    let pred_lat = display_lat + ratio * (data.target_lat - display_lat);
                                    let pred_lon = display_lon + ratio * (data.target_lon - display_lon);
                                    
                                    let dy = pred_lat - display_lat;
                                    let dx = Math.cos(Math.PI/180 * display_lat) * (pred_lon - display_lon);
                                    let targetBearing = Math.atan2(dx, dy) * 180 / Math.PI;
                                    if (targetBearing < 0) targetBearing += 360;

                                    let ghostHtml = `<div style="transform: rotate(${{targetBearing}}deg); transform-origin: center center; opacity: 0.5;">
                                        <svg viewBox="0 0 100 100" width="45" height="45" xmlns="http://www.w3.org/2000/svg">
                                            <line x1="20" y1="20" x2="80" y2="80" stroke="${{color}}" stroke-width="6" stroke-dasharray="4,4"/>
                                            <line x1="20" y1="80" x2="80" y2="20" stroke="${{color}}" stroke-width="6" stroke-dasharray="4,4"/>
                                            <circle cx="20" cy="20" r="14" fill="none" stroke="${{color}}" stroke-width="3" stroke-dasharray="4,4"/>
                                            <circle cx="80" cy="80" r="14" fill="none" stroke="${{color}}" stroke-width="3" stroke-dasharray="4,4"/>
                                            <circle cx="20" cy="80" r="14" fill="none" stroke="${{color}}" stroke-width="3" stroke-dasharray="4,4"/>
                                            <circle cx="80" cy="20" r="14" fill="none" stroke="${{color}}" stroke-width="3" stroke-dasharray="4,4"/>
                                            <circle cx="50" cy="50" r="12" fill="${{color}}"/>
                                            <polygon points="50,5 35,30 65,30" fill="#f1c40f"/>
                                        </svg>
                                        <div style="color:#f1c40f; font-weight:bold; font-size:12px; position:absolute; top:-20px; left:-15px; white-space:nowrap; text-shadow: 1px 1px 2px #000; transform: rotate(-${{targetBearing}}deg);">
                                            5s 预测点
                                        </div>
                                    </div>`;

                                    if (!ghostMarkers[did]) {{
                                        ghostMarkers[did] = new AMap.Marker({{ position: [pred_lon, pred_lat], content: ghostHtml, offset: new AMap.Pixel(-22.5, -22.5), anchor: 'center', zIndex: 140 }});
                                        map.add(ghostMarkers[did]);
                                        
                                        predictLines[did] = new AMap.Polyline({{ path: [[display_lon, display_lat], [pred_lon, pred_lat]], strokeColor: "#f1c40f", strokeWeight: 2, strokeStyle: "dashed", strokeDasharray: [10, 5], zIndex: 130 }});
                                        map.add(predictLines[did]);
                                    }} else {{
                                        ghostMarkers[did].setPosition([pred_lon, pred_lat]);
                                        ghostMarkers[did].setContent(ghostHtml);
                                        ghostMarkers[did].show();
                                        
                                        predictLines[did].setPath([[display_lon, display_lat], [pred_lon, pred_lat]]);
                                        predictLines[did].show();
                                    }}
                                }}
                            }}
                            
                            if (!showGhost) {{
                                if (ghostMarkers[did]) ghostMarkers[did].hide();
                                if (predictLines[did]) predictLines[did].hide();
                            }}

                            if (did === current_id && current_lat !== 0 && current_lat !== 22.54 && !hasCenteredMap) {{
                                map.setCenter([current_lon, current_lat]);
                                map.setZoom(18); 
                                hasCenteredMap = true; 
                            }}
                        }}
                    }}
                }} 
                else if (msg.type === "mission_downloaded") {{
                    if (msg.drone_id === current_id) {{
                        clearMission();
                        if (msg.waypoints.length === 0) {{
                            alert("飞控中没有航点或读取失败！"); return;
                        }}
                        msg.waypoints.forEach(wp => {{ addWpRow(wp.cmd, wp.lat, wp.lon, wp.alt); }});
                        alert(`成功读取了 ${{msg.waypoints.length}} 个航点！`);
                    }}
                }}
            }};

            function cmd(c, v) {{ 
                if(!current_id) return alert("请先添加并选择无人机！");
                sendControlCmd({{ drone_id: current_id, command: c, val: v }}); 
            }}
            
            // 【新增 JS】：处理强制解锁逻辑
            function forceArm() {{
                if(!current_id) return alert("请先添加并选择无人机！");
                if(confirm("⚠️ 极度危险操作！\\n强制解锁 (FORCE ARM) 会直接跳过 GPS、罗盘、机架等所有安全检查，无论状态如何立刻启动电机！\\n\\n你确定要在当前无人机上执行 FORCE ARM 吗？")) {{
                    sendControlCmd({{ drone_id: current_id, command: "FORCE_ARM" }});
                }}
            }}

            function moveRel(dirX, dirY) {{
                if(!current_id) return alert("请先选择无人机！");
                const dist = parseFloat(document.getElementById('in_move_dist').value);
                if(isNaN(dist) || dist <= 0) return alert("请输入有效距离");
                
                sendControlCmd({{
                    drone_id: current_id, 
                    command: "MOVE_RELATIVE",
                    dx: dirX * dist,
                    dy: dirY * dist,
                    dz: 0
                }});
            }}

            function executeGuidedFly() {{
                if (!ctx_target || !current_id) return;
                sendControlCmd({{
                    drone_id: current_id, command: "GUIDED_FLY",
                    lat: ctx_target.lat, lon: ctx_target.lon,
                    alt: document.getElementById('ctx_alt').value,
                    speed: document.getElementById('ctx_spd').value,
                    yaw: document.getElementById('ctx_yaw').value
                }});
                closeCtxMenu();
            }}

            function gcmd(act, v1, v2) {{
                if(!current_id) return;
                let cmdType = "GIMBAL_DIR";
                let valToSend = act;

                if (act === 'zoom') {{
                    cmdType = "GIMBAL_ZOOM";
                    valToSend = v1;
                }} else if (act === 'set_angle') {{
                    cmdType = "GIMBAL_SET";
                }}

                sendControlCmd({{ 
                    drone_id: current_id, command: cmdType, val: valToSend, yaw: v1, pitch: v2 
                }});
            }}

            let selectedRowIndex = -1;
            
            function refreshMapWps() {{
                wpMarkers.forEach(m => map.remove(m)); wpMarkers = [];
                const table = document.getElementById('msn_table');
                for(let i=1; i<table.rows.length; i++) {{
                    const selectEl = table.rows[i].cells[0].querySelector('select');
                    const cmd = selectEl ? selectEl.value : table.rows[i].cells[0].innerText;
                    const lat = parseFloat(table.rows[i].cells[1].innerText);
                    const lon = parseFloat(table.rows[i].cells[2].innerText);
                    
                    let txt = i.toString();
                    if(cmd === "TAKEOFF") txt = "TO"; if(cmd === "RTL") txt = "RTL"; if(cmd === "LAND") txt = "LND";
                    
                    const marker = new AMap.LabelMarker({{
                        position: [lon, lat], text: {{ content: txt, direction: 'center', style: {{ fontSize: 13, fillColor: '#fff' }} }},
                        icon: {{ image: 'https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png', size: [19, 31], anchor: 'bottom-center' }}
                    }});
                    map.add(marker); wpMarkers.push(marker);
                }}
            }}

            function addWpRow(cmd, lat, lon, alt) {{
                const table = document.getElementById('msn_table');
                const row = table.insertRow(-1);
                row.onclick = function(e) {{ 
                    for(let i=1; i<table.rows.length; i++) table.rows[i].classList.remove('selected-row');
                    row.classList.add('selected-row');
                    selectedRowIndex = row.rowIndex;
                }};
                
                const opts = ["WAYPOINT", "TAKEOFF", "RTL", "LAND"];
                let selectHtml = `<select onchange="refreshMapWps()" style="background:#2c3e50; color:white; border:1px solid #7f8c8d; border-radius:4px; padding:2px; font-size:12px; width:90%;">`;
                opts.forEach(opt => {{
                    const sel = opt === cmd ? "selected" : "";
                    selectHtml += `<option value="${{opt}}" ${{sel}}>${{opt}}</option>`;
                }});
                selectHtml += `</select>`;

                row.innerHTML = `<td>${{selectHtml}}</td><td contenteditable="true" style="background:#2c3e50">${{lat.toFixed(6)}}</td><td contenteditable="true" style="background:#2c3e50">${{lon.toFixed(6)}}</td><td contenteditable="true" style="background:#2c3e50">${{alt.toFixed(1)}}</td>`;
                refreshMapWps();
            }}

            function initMission() {{ clearMission(); addWpRow('TAKEOFF', current_lat, current_lon, 10.0); addWpRow('RTL', 0, 0, 0); }}
            
            function clearMission() {{
                const table = document.getElementById('msn_table');
                while(table.rows.length > 1) table.deleteRow(1);
                selectedRowIndex = -1; refreshMapWps();
            }}

            function deleteRow() {{
                if(selectedRowIndex > 0) {{ document.getElementById('msn_table').deleteRow(selectedRowIndex); selectedRowIndex = -1; refreshMapWps(); }}
            }}

            function moveRow(dir) {{
                if(selectedRowIndex <= 0) return;
                const table = document.getElementById('msn_table');
                const targetIdx = selectedRowIndex + dir;
                if(targetIdx > 0 && targetIdx < table.rows.length) {{
                    const rows = table.rows;
                    const parent = rows[selectedRowIndex].parentNode;
                    if(dir === -1) parent.insertBefore(rows[selectedRowIndex], rows[targetIdx]);
                    else parent.insertBefore(rows[targetIdx], rows[selectedRowIndex]);
                    selectedRowIndex = targetIdx; refreshMapWps();
                }}
            }}

            function exportJSON() {{
                const table = document.getElementById('msn_table');
                const wps = [];
                for(let i=1; i<table.rows.length; i++) {{
                    const selectEl = table.rows[i].cells[0].querySelector('select');
                    wps.push({{
                        cmd: selectEl ? selectEl.value : table.rows[i].cells[0].innerText,
                        lat: parseFloat(table.rows[i].cells[1].innerText),
                        lon: parseFloat(table.rows[i].cells[2].innerText),
                        alt: parseFloat(table.rows[i].cells[3].innerText)
                    }});
                }}
                const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(wps, null, 2));
                const dlAnchorElem = document.createElement('a');
                dlAnchorElem.setAttribute("href", dataStr);
                dlAnchorElem.setAttribute("download", "waypoints.json");
                dlAnchorElem.click();
            }}

            function importJSON(event) {{
                const file = event.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(e) {{
                    try {{
                        const wps = JSON.parse(e.target.result);
                        clearMission();
                        wps.forEach(wp => {{ addWpRow(wp.cmd, wp.lat, wp.lon, wp.alt); }});
                        alert("成功导入 " + wps.length + " 个航点");
                    }} catch(err) {{
                        alert("JSON 解析失败: " + err.message);
                    }}
                }};
                reader.readAsText(file);
                event.target.value = ""; 
            }}

            function uploadMission() {{
                if(!current_id) return alert("请先添加并选择无人机！");
                const table = document.getElementById('msn_table');
                const wps = [];
                for(let i=1; i<table.rows.length; i++) {{
                    const selectEl = table.rows[i].cells[0].querySelector('select');
                    wps.push({{
                        cmd: selectEl ? selectEl.value : table.rows[i].cells[0].innerText,
                        lat: parseFloat(table.rows[i].cells[1].innerText),
                        lon: parseFloat(table.rows[i].cells[2].innerText),
                        alt: parseFloat(table.rows[i].cells[3].innerText)
                    }});
                }}
                ws_send({{ drone_id: current_id, command: "UPLOAD_MISSION", waypoints: wps }});
                alert("已发送航点任务上传指令，请观察后台打印输出！");
            }}

            function downloadMission() {{
                if(!current_id) return alert("请先添加并选择无人机！");
                ws_send({{ drone_id: current_id, command: "DOWNLOAD_MISSION" }});
                alert("已发送读取指令，正在从飞控拉取航点...");
            }}

            let pc = null;
            async function startVideo() {{
                stopVideo();
                const whepUrl = document.getElementById('in_whep').value;
                if(!whepUrl) return;
                
                pc = new RTCPeerConnection();
                pc.addTransceiver('video', {{ direction: 'recvonly' }});
                pc.ontrack = (event) => {{ document.getElementById('video_player').srcObject = event.streams[0]; }};
                
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                try {{
                    const response = await fetch(whepUrl, {{ method: 'POST', body: pc.localDescription.sdp, headers: {{ 'Content-Type': 'application/sdp' }} }});
                    const answerSdp = await response.text();
                    await pc.setRemoteDescription({{ type: 'answer', sdp: answerSdp }});
                }} catch (e) {{ alert("视频连接失败: " + e.message); }}
            }}

            function stopVideo() {{
                if(pc) {{ pc.close(); pc = null; document.getElementById('video_player').srcObject = null; }}
            }}
            
            function getOfflineDistance(lat1, lon1, lat2, lon2) {{
                if (!lat1 || !lon1 || !lat2 || !lon2) return 0;
                const R = 6378137; 
                const dLat = (lat2 - lat1) * Math.PI / 180;
                const dLon = (lon2 - lon1) * Math.PI / 180;
                const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
                const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                return R * c;
            }}

        </script>
    </body>
    </html>
    """
    return html

    
@app.get("/")
def get_ui():
    return HTMLResponse(content=generate_html())

if __name__ == "__main__":
    print("🚀 多机协同 Web 地面站已启动！(新增：原声飞控报错弹窗 + 强制解锁(Force Arm) 功能)")
    
    # 获取用户输入
    try:
        num_input = input("❓ 请输入要自动连接的模拟器数量 (按回车默认 10台): ")
        NUM_DRONES = int(num_input) if num_input.strip() else 10
    except:
        NUM_DRONES = 10

    # --- 开机自动连接 N 个模拟器的后台任务 ---
    def auto_connect_sims(num):
        print(f"⏳ 正在后台批量连接 {num} 个模拟器...")
        for i in range(num):
            d_id = f"sim_drone_{i+1}"
            port = 5760 + (i * 10)  
            nodes[d_id] = DroneNode({
                "id": d_id,
                "name": f"模拟器 {i+1}",
                "fcu_url": f"tcp:127.0.0.1:{port}",
                "baudrate": 57600,
                "rtsp_url": "",
                "mqtt_ip": ""
            })
            time.sleep(0.3) 
            
        print(f"✅ {num} 台模拟器连接指令已全部下发！")

    threading.Thread(target=auto_connect_sims, args=(NUM_DRONES,), daemon=True).start()

    print("🌐 请在任何设备的浏览器中打开: http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)