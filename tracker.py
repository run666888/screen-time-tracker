"""
屏幕使用时间 - 后台采集程序
静默运行，监控活动窗口、空闲时间、通知统计，写入SQLite
"""
import os
import sys
import time
import json
import sqlite3
import threading
import signal
from datetime import datetime, timedelta
from pathlib import Path

# 将项目目录加入sys.path
PROJECT_DIR = Path(__file__).parent
os.chdir(str(PROJECT_DIR))

DB_PATH = PROJECT_DIR / "screentime.db"

try:
    import psutil
    import win32gui
    import win32process
    import win32api
    import win32con
    from ctypes import Structure, windll, c_uint, sizeof, byref
except ImportError as e:
    print(f"依赖缺失: {e}")
    sys.exit(1)

# ============================================================
# 空闲检测 - GetLastInputInfo
# ============================================================
class LASTINPUTINFO(Structure):
    _fields_ = [
        ('cbSize', c_uint),
        ('dwTime', c_uint),
    ]

def get_idle_seconds():
    """返回自上次用户输入以来的空闲秒数"""
    lii = LASTINPUTINFO()
    lii.cbSize = sizeof(LASTINPUTINFO)
    windll.user32.GetLastInputInfo(byref(lii))
    millis = windll.kernel32.GetTickCount() - lii.dwTime
    return millis / 1000.0

IDLE_THRESHOLD = 300  # 5分钟

# ============================================================
# 数据库
# ============================================================
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # 活动窗口记录 - 每5秒一条
    c.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            process_name TEXT NOT NULL,
            window_title TEXT,
            is_foreground INTEGER DEFAULT 1,
            is_idle INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 5.0
        )
    ''')

    # 每日汇总
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            process_name TEXT NOT NULL,
            total_seconds REAL DEFAULT 0,
            foreground_seconds REAL DEFAULT 0,
            background_seconds REAL DEFAULT 0,
            open_count INTEGER DEFAULT 0,
            notification_count INTEGER DEFAULT 0,
            UNIQUE(date, process_name)
        )
    ''')

    # 通知记录
    c.execute('''
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            app_name TEXT NOT NULL,
            title TEXT,
            body TEXT
        )
    ''')

    # 空闲时段
    c.execute('''
        CREATE TABLE IF NOT EXISTS idle_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_seconds REAL DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()

# ============================================================
# 活动窗口监控
# ============================================================
def get_foreground_process():
    """获取当前前台窗口的进程名"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name(), win32gui.GetWindowText(hwnd)
    except Exception:
        return None, None

def get_running_processes():
    """获取所有有窗口的进程名（后台运行）"""
    processes = set()

    def enum_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                p = psutil.Process(pid)
                processes.add(p.name())
            except Exception:
                pass
        return True

    win32gui.EnumWindows(enum_callback, None)
    return processes

# ============================================================
# 通知统计 - 读取 wpndatabase.db
# ============================================================
def get_notification_count():
    """读取Windows通知数据库，返回通知统计"""
    wpn_path = os.path.expandvars(
        r'%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db'
    )
    if not os.path.exists(wpn_path):
        return []

    # 尝试复制后读取
    import tempfile
    import shutil

    tmp_path = os.path.join(tempfile.gettempdir(), 'wpn_temp.db')
    try:
        shutil.copy2(wpn_path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        c = conn.cursor()

        # 查询最近的通知
        c.execute('''
            SELECT
                datetime(ArrivalTime / 10000000 - 11644473600, 'unixepoch', 'localtime') as time,
                AppId,
                Payload
            FROM Notification
            WHERE ArrivalTime IS NOT NULL
            ORDER BY ArrivalTime DESC
            LIMIT 200
        ''')
        results = []
        for row in c.fetchall():
            time_str, app_id, payload = row
            # 提取应用名
            app_name = app_id.split('!')[0] if '!' in app_id else app_id
            if '.' in app_name:
                app_name = app_name.rsplit('.', 1)[-1]
            title = ''
            body = ''
            if payload:
                try:
                    data = json.loads(payload)
                    title = data.get('title', '') or ''
                    body = data.get('body', '') or ''
                except Exception:
                    pass
            results.append({
                'timestamp': time_str,
                'app_name': app_name,
                'title': title,
                'body': body
            })
        conn.close()
        return results
    except Exception:
        return []
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

# ============================================================
# 数据聚合
# ============================================================
def aggregate_daily():
    """聚合活动记录到每日统计"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    # 从 activity_log 聚合当天数据
    c.execute('''
        SELECT
            process_name,
            SUM(CASE WHEN is_foreground=1 AND is_idle=0 THEN duration_seconds ELSE 0 END) as fg_time,
            SUM(CASE WHEN is_foreground=0 AND is_idle=0 THEN duration_seconds ELSE 0 END) as bg_time,
            COUNT(DISTINCT CASE WHEN is_foreground=1 THEN
                substr(timestamp,1,16) || process_name
            END) as opens
        FROM activity_log
        WHERE date(timestamp) = ?
        GROUP BY process_name
    ''', (today,))

    for proc, fg, bg, opens in c.fetchall():
        c.execute('''
            INSERT INTO daily_stats (date, process_name, total_seconds,
                foreground_seconds, background_seconds, open_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, process_name) DO UPDATE SET
                total_seconds = total_seconds + ?,
                foreground_seconds = foreground_seconds + ?,
                background_seconds = background_seconds + ?,
                open_count = open_count + ?
        ''', (today, proc, fg + bg, fg, bg, opens or 1,
              fg + bg, fg, bg, opens or 1))

    conn.commit()
    conn.close()

# ============================================================
# 主循环
# ============================================================
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 屏幕使用时间追踪已启动")
    init_db()

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    last_process = None
    last_foreground = True
    process_start_time = time.time()
    last_aggregate = time.time()
    last_notification_check = 0
    known_notifications = set()
    idle_start = None
    in_idle = False

    try:
        while True:
            now = time.time()
            idle_secs = get_idle_seconds()
            is_idle = idle_secs > IDLE_THRESHOLD
            ts = datetime.now().strftime('%Y-%m-%d %H:%M')

            # 记录空闲状态
            if is_idle and not in_idle:
                in_idle = True
                idle_start = datetime.now().strftime('%Y-%m-%d %H:%M')
            elif not is_idle and in_idle:
                in_idle = False
                if idle_start:
                    idle_end = datetime.now().strftime('%Y-%m-%d %H:%M')
                    idle_dur = idle_secs
                    c.execute('''
                        INSERT INTO idle_periods (start_time, end_time, duration_seconds)
                        VALUES (?, ?, ?)
                    ''', (idle_start, idle_end, idle_dur))
                    conn.commit()
                    idle_start = None

            if not is_idle:
                proc_name, win_title = get_foreground_process()

                if proc_name:
                    # 前台进程
                    if proc_name != last_process:
                        duration = now - process_start_time
                        if last_process and duration > 0:
                            c.execute('''
                                INSERT INTO activity_log
                                (timestamp, process_name, window_title, is_foreground, is_idle, duration_seconds)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (ts, last_process, '', 1, 0, duration))

                        process_start_time = now
                        last_process = proc_name

                    # 后台进程
                    all_procs = get_running_processes()
                    for bg_proc in all_procs:
                        if bg_proc != proc_name:
                            c.execute('''
                                INSERT INTO activity_log
                                (timestamp, process_name, window_title, is_foreground, is_idle, duration_seconds)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (ts, bg_proc, '', 0, 0, 5.0))
                else:
                    # 无法获取前台进程，记录当前所有窗口进程
                    all_procs = get_running_processes()
                    for p in all_procs:
                        c.execute('''
                            INSERT INTO activity_log
                            (timestamp, process_name, window_title, is_foreground, is_idle, duration_seconds)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (ts, p, '', 0, 0, 5.0))

                conn.commit()

            else:
                # 空闲中，写一条空闲记录
                c.execute('''
                    INSERT INTO activity_log
                    (timestamp, process_name, window_title, is_foreground, is_idle, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (ts, 'IDLE', '', 0, 1, 5.0))
                conn.commit()

            # 每5分钟检查通知
            if now - last_notification_check > 300:
                notifications = get_notification_count()
                for n in notifications:
                    nkey = f"{n['timestamp']}_{n['app_name']}_{n['title']}"
                    if nkey not in known_notifications:
                        known_notifications.add(nkey)
                        c.execute('''
                            INSERT INTO notification_log (timestamp, app_name, title, body)
                            VALUES (?, ?, ?, ?)
                        ''', (n['timestamp'], n['app_name'], n['title'], n['body']))

                        # 更新每日统计的通知数
                        n_date = n['timestamp'][:10] if n['timestamp'] else datetime.now().strftime('%Y-%m-%d')
                        c.execute('''
                            INSERT INTO daily_stats (date, process_name, total_seconds,
                                foreground_seconds, background_seconds, open_count, notification_count)
                            VALUES (?, ?, 0, 0, 0, 0, 1)
                            ON CONFLICT(date, process_name) DO UPDATE SET
                                notification_count = notification_count + 1
                        ''', (n_date, n['app_name']))
                conn.commit()
                last_notification_check = now

            # 每小时聚合一次
            if now - last_aggregate > 3600:
                aggregate_daily()
                last_aggregate = now

            time.sleep(5)

    except KeyboardInterrupt:
        print("采集程序已停止")
    finally:
        # 最后做一次聚合
        aggregate_daily()
        conn.close()

if __name__ == '__main__':
    main()
