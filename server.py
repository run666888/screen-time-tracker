"""
屏幕使用时间 - Flask Web面板
端口19999，iOS风格UI，全部前端内嵌
"""
import os
import sys
import sqlite3
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent
os.chdir(str(PROJECT_DIR))
DB_PATH = PROJECT_DIR / "screentime.db"

from flask import Flask, jsonify, request

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        process_name TEXT NOT NULL, window_title TEXT,
        is_foreground INTEGER DEFAULT 1, is_idle INTEGER DEFAULT 0,
        duration_seconds REAL DEFAULT 5.0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
        process_name TEXT NOT NULL, total_seconds REAL DEFAULT 0,
        foreground_seconds REAL DEFAULT 0, background_seconds REAL DEFAULT 0,
        open_count INTEGER DEFAULT 0, notification_count INTEGER DEFAULT 0,
        UNIQUE(date, process_name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        app_name TEXT NOT NULL, title TEXT, body TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS idle_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, start_time TEXT NOT NULL,
        end_time TEXT, duration_seconds REAL DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

app = Flask(__name__)

# ============================================================
# API
# ============================================================
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def get_date_range(period):
    """根据period返回日期范围"""
    today = datetime.now()
    if period == 'today':
        return today.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
        return start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    elif period == 'month':
        start = today.replace(day=1)
        return start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    return today.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')

@app.route('/api/stats')
def api_stats():
    period = request.args.get('period', 'today')
    start_date, end_date = get_date_range(period)

    conn = get_db()
    c = conn.cursor()

    # 总使用时间
    c.execute('''
        SELECT COALESCE(SUM(total_seconds), 0)
        FROM daily_stats
        WHERE date BETWEEN ? AND ?
    ''', (start_date, end_date))
    total_seconds = c.fetchone()[0]

    # 各软件统计
    c.execute('''
        SELECT process_name,
               SUM(total_seconds) as total_sec,
               SUM(foreground_seconds) as fg_sec,
               SUM(background_seconds) as bg_sec,
               SUM(open_count) as opens,
               SUM(notification_count) as notifs
        FROM daily_stats
        WHERE date BETWEEN ? AND ?
        GROUP BY process_name
        ORDER BY total_sec DESC
        LIMIT 50
    ''', (start_date, end_date))

    apps = []
    for row in c.fetchall():
        apps.append({
            'name': row['process_name'],
            'total_seconds': round(row['total_sec'], 1),
            'foreground_seconds': round(row['fg_sec'], 1),
            'background_seconds': round(row['bg_sec'], 1),
            'open_count': row['opens'] or 0,
            'notification_count': row['notifs'] or 0
        })

    # 每小时时间线数据
    c.execute('''
        SELECT
            substr(timestamp, 12, 2) as hour,
            SUM(CASE WHEN is_foreground=1 AND is_idle=0 THEN duration_seconds ELSE 0 END) as active_sec
        FROM activity_log
        WHERE date(timestamp) BETWEEN ? AND ?
        GROUP BY hour
        ORDER BY hour
    ''', (start_date, end_date))
    hourly = {}
    for row in c.fetchall():
        hourly[int(row['hour'])] = round(row['active_sec'], 1)

    # 每日总计（用于趋势图）
    if period in ('week', 'month'):
        c.execute('''
            SELECT date, SUM(total_seconds) as day_total
            FROM daily_stats
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
        ''', (start_date, end_date))
        daily_totals = {row['date']: round(row['day_total'], 1) for row in c.fetchall()}
    else:
        daily_totals = None

    conn.close()

    return jsonify({
        'total_seconds': round(total_seconds, 1),
        'apps': apps,
        'hourly': hourly,
        'daily_totals': daily_totals,
        'period': period,
        'start_date': start_date,
        'end_date': end_date
    })

@app.route('/api/advice')
def api_advice():
    """基于真实数据的使用建议"""
    conn = get_db()
    c = conn.cursor()

    # 检查数据天数
    c.execute('SELECT COUNT(DISTINCT date) FROM daily_stats')
    day_count = c.fetchone()[0]

    if day_count < 3:
        conn.close()
        return jsonify({
            'ready': False,
            'message': '数据不足3天，再用几天才能给出使用建议',
            'days': day_count
        })

    advice = []

    # 今日 vs 历史平均
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute('''
        SELECT process_name, SUM(total_seconds) as today_sec
        FROM daily_stats
        WHERE date = ?
        GROUP BY process_name
        ORDER BY today_sec DESC
        LIMIT 20
    ''', (today,))
    today_apps = {row['process_name']: row['today_sec'] for row in c.fetchall()}

    # 历史平均（不含今天）
    c.execute('''
        SELECT process_name, AVG(daily_total) as avg_sec
        FROM (
            SELECT date, process_name, SUM(total_seconds) as daily_total
            FROM daily_stats
            WHERE date < ?
            GROUP BY date, process_name
        )
        GROUP BY process_name
    ''', (today,))
    history_avg = {row['process_name']: row['avg_sec'] for row in c.fetchall()}

    for app_name, today_sec in today_apps.items():
        if app_name in history_avg and history_avg[app_name] > 0:
            ratio = today_sec / history_avg[app_name]
            if ratio > 2.0:
                advice.append(f"今天 {app_name.replace('.exe','')} 的使用时间是平时的 {ratio:.1f} 倍，远超平均水平")

    # 晚间娱乐软件使用
    evening_entertainment = ['chrome.exe', 'msedge.exe', 'firefox.exe',
                              'steam.exe', 'epicgameslauncher.exe',
                              'bilibili.exe', 'douyin.exe', 'youtube.exe',
                              'qq.exe', 'wechat.exe', 'telegram.exe']
    c.execute('''
        SELECT process_name, SUM(duration_seconds) as sec
        FROM activity_log
        WHERE date(timestamp) = ?
          AND is_foreground = 1
          AND is_idle = 0
          AND CAST(substr(timestamp, 12, 2) AS INTEGER) >= 22
        GROUP BY process_name
        ORDER BY sec DESC
    ''', (today,))
    for row in c.fetchall():
        proc = row['process_name']
        if proc.lower() in [e.lower() for e in evening_entertainment]:
            if row['sec'] > 1800:  # 超过30分钟
                advice.append(f"晚上10点后 {proc.replace('.exe','')} 使用了 {int(row['sec']//60)} 分钟，建议减少晚间屏幕时间")

    # 长时间连续使用
    c.execute('''
        SELECT process_name, SUM(duration_seconds) as sec
        FROM activity_log
        WHERE date(timestamp) = ?
          AND is_foreground = 1
          AND is_idle = 0
        GROUP BY process_name
        HAVING sec > 7200
        ORDER BY sec DESC
    ''', (today,))
    for row in c.fetchall():
        advice.append(f"今天 {row['process_name'].replace('.exe','')} 累计使用 {int(row['sec']//60)} 分钟，建议适时休息")

    # 通知过多
    c.execute('''
        SELECT app_name, COUNT(*) as cnt
        FROM notification_log
        WHERE date(timestamp) = ?
        GROUP BY app_name
        HAVING cnt > 20
        ORDER BY cnt DESC
    ''', (today,))
    for row in c.fetchall():
        advice.append(f"今天 {row['app_name']} 推送了 {row['cnt']} 条通知，可以关闭不必要的通知减少干扰")

    conn.close()

    return jsonify({
        'ready': True,
        'advice': advice[:5],
        'days': day_count
    })

@app.route('/api/live')
def api_live():
    """实时数据 - 当前前台进程"""
    try:
        import win32gui
        import win32process
        import psutil
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        name = proc.name()
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        name = ''
        title = ''

    return jsonify({
        'current_app': name,
        'window_title': title,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

# ============================================================
# HTML 内嵌
# ============================================================
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>屏幕使用时间</title>
<style>
:root {
    --bg: #000000;
    --card-bg: #1C1C1E;
    --text: #FFFFFF;
    --text-secondary: #8E8E93;
    --accent: #5E5CE6;
    --accent-light: #7D7BF0;
    --divider: #2C2C2E;
    --red: #FF453A;
    --orange: #FF9F0A;
    --blue: #0A84FF;
    --green: #30D158;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
}
.container { max-width: 900px; margin: 0 auto; padding: 20px; }

/* Header */
.header {
    text-align: center;
    padding: 30px 0 10px;
}
.header h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
}
.header .subtitle {
    color: var(--text-secondary);
    font-size: 14px;
    margin-top: 4px;
}

/* Time Summary Card */
.summary-card {
    background: var(--card-bg);
    border-radius: 20px;
    padding: 28px 24px;
    margin: 16px 0;
    text-align: center;
}
.summary-card .total-time {
    font-size: 56px;
    font-weight: 700;
    letter-spacing: -1px;
    color: var(--accent-light);
}
.summary-card .total-label {
    color: var(--text-secondary);
    font-size: 15px;
    margin-top: 4px;
}
.summary-card .stats-row {
    display: flex;
    justify-content: center;
    gap: 40px;
    margin-top: 20px;
}
.stat-item .stat-value {
    font-size: 22px;
    font-weight: 600;
}
.stat-item .stat-label {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 2px;
}

/* Period Selector */
.period-selector {
    display: flex;
    background: var(--card-bg);
    border-radius: 12px;
    padding: 4px;
    margin: 16px 0;
}
.period-btn {
    flex: 1;
    padding: 10px 16px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 10px;
    transition: all 0.2s;
    font-family: inherit;
}
.period-btn.active {
    background: var(--accent);
    color: white;
    font-weight: 600;
}

/* Hourly Timeline */
.timeline {
    background: var(--card-bg);
    border-radius: 16px;
    padding: 20px;
    margin: 16px 0;
    position: relative;
}
.timeline-title {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.timeline-bars {
    display: flex;
    align-items: flex-end;
    gap: 3px;
    height: 120px;
    cursor: pointer;
}
.timeline-bar {
    flex: 1;
    background: var(--accent);
    border-radius: 3px 3px 0 0;
    min-height: 1px;
    transition: opacity 0.2s;
    position: relative;
}
.timeline-bar:hover {
    opacity: 0.8;
}
.timeline-bar.active {
    background: var(--accent-light);
}
.timeline-labels {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    font-size: 10px;
    color: var(--text-secondary);
}

/* Daily Trend (week/month) */
.daily-timeline {
    display: flex;
    align-items: flex-end;
    gap: 6px;
    height: 100px;
}
.daily-bar {
    flex: 1;
    background: var(--accent);
    border-radius: 3px 3px 0 0;
    min-height: 2px;
    transition: opacity 0.2s;
    cursor: pointer;
}
.daily-bar:hover { opacity: 0.8; }
.daily-bar.active { background: var(--accent-light); }

/* App List */
.app-list-card {
    background: var(--card-bg);
    border-radius: 16px;
    padding: 6px 0;
    margin: 16px 0;
    overflow: hidden;
}
.app-item {
    display: flex;
    align-items: center;
    padding: 12px 20px;
    transition: background 0.15s;
    border-bottom: 1px solid var(--divider);
}
.app-item:last-child { border-bottom: none; }
.app-item:hover { background: rgba(255,255,255,0.04); }
.app-icon {
    width: 36px;
    height: 36px;
    border-radius: 9px;
    background: var(--divider);
    margin-right: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
    overflow: hidden;
}
.app-icon.placeholder {
    color: var(--accent-light);
    font-weight: 700;
    font-size: 15px;
}
.app-info { flex: 1; min-width: 0; }
.app-name {
    font-size: 16px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.app-detail {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 2px;
}
.app-time {
    font-size: 15px;
    font-weight: 500;
    color: var(--text);
    min-width: 60px;
    text-align: right;
}

.app-badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    margin-left: 8px;
    font-weight: 500;
}
.badge-notif { background: rgba(255,69,58,0.2); color: var(--red); }
.badge-bg { background: rgba(142,142,147,0.2); color: var(--text-secondary); }

/* Advice */
.advice-card {
    background: var(--card-bg);
    border-radius: 16px;
    padding: 20px;
    margin: 16px 0;
}
.advice-title {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.advice-item {
    padding: 10px 0;
    border-bottom: 1px solid var(--divider);
    font-size: 14px;
    line-height: 1.5;
    display: flex;
    align-items: flex-start;
    gap: 10px;
}
.advice-item:last-child { border-bottom: none; }
.advice-icon {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    flex-shrink: 0;
    margin-top: 1px;
}
.advice-warn { background: rgba(255,159,10,0.2); color: var(--orange); }
.advice-info { background: rgba(10,132,255,0.2); color: var(--blue); }

/* Loading & Errors */
.loading {
    text-align: center;
    padding: 40px;
    color: var(--text-secondary);
}
.spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--divider);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 10px;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Live indicator */
.live-indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--green);
    padding: 4px 12px;
    background: rgba(48,209,88,0.1);
    border-radius: 12px;
}
.live-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Responsive */
@media (max-width: 600px) {
    .container { padding: 12px; }
    .summary-card .total-time { font-size: 44px; }
    .stats-row { gap: 20px; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>屏幕使用时间</h1>
        <div class="subtitle">
            <span class="live-indicator"><span class="live-dot"></span>实时监控中</span>
        </div>
    </div>

    <!-- Summary Card -->
    <div class="summary-card" id="summaryCard">
        <div class="total-time" id="totalTime">--</div>
        <div class="total-label" id="totalLabel">今日使用时长</div>
        <div class="stats-row">
            <div class="stat-item">
                <div class="stat-value" id="appCount">--</div>
                <div class="stat-label">使用软件数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="notifCount">--</div>
                <div class="stat-label">通知数量</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="topApp">--</div>
                <div class="stat-label">最常用</div>
            </div>
        </div>
    </div>

    <!-- Period Selector -->
    <div class="period-selector" id="periodSelector">
        <button class="period-btn active" data-period="today">今日</button>
        <button class="period-btn" data-period="week">本周</button>
        <button class="period-btn" data-period="month">本月</button>
    </div>

    <!-- Timeline -->
    <div class="timeline" id="timelineCard">
        <div class="timeline-title">使用时段</div>
        <div class="timeline-bars" id="timelineBars"></div>
        <div class="timeline-labels" id="timelineLabels"></div>
    </div>

    <!-- App List -->
    <div class="app-list-card" id="appList">
        <div class="loading"><div class="spinner"></div>加载中...</div>
    </div>

    <!-- Advice -->
    <div class="advice-card" id="adviceCard">
        <div class="advice-title">使用建议</div>
        <div id="adviceContent"><div class="loading"><div class="spinner"></div>分析中...</div></div>
    </div>
</div>

<script>
let currentPeriod = 'today';
let currentHour = -1;
let currentDay = '';

// Format seconds to readable time
function formatTime(seconds) {
    if (seconds < 60) return Math.round(seconds) + '秒';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return h + '小时 ' + m + '分';
    return m + '分钟';
}

function formatTimeShort(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
}

function getAppInitial(name) {
    const n = name.replace('.exe', '').replace('.EXE', '');
    if (n.length <= 2) return n.toUpperCase();
    return n.substring(0, 2).toUpperCase();
}

function getAppDisplayName(name) {
    return name.replace('.exe', '').replace('.EXE', '');
}

// Period selector
document.getElementById('periodSelector').addEventListener('click', function(e) {
    if (e.target.classList.contains('period-btn')) {
        document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        currentPeriod = e.target.dataset.period;
        currentHour = -1;
        currentDay = '';
        loadData();
    }
});

// Timeline click handler
document.getElementById('timelineBars').addEventListener('click', function(e) {
    const bar = e.target.closest('.timeline-bar');
    const dailyBar = e.target.closest('.daily-bar');
    if (bar && bar.dataset.hour !== undefined) {
        currentHour = parseInt(bar.dataset.hour);
        applyHourFilter();
    }
    if (dailyBar && dailyBar.dataset.day !== undefined) {
        currentDay = dailyBar.dataset.day;
        applyDayFilter();
    }
});

function applyHourFilter() {
    document.querySelectorAll('.timeline-bar').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.hour) === currentHour);
    });
    renderAppList(window.lastData);
}

function applyDayFilter() {
    document.querySelectorAll('.daily-bar').forEach(b => {
        b.classList.toggle('active', b.dataset.day === currentDay);
    });
    if (currentDay) {
        // Filter apps for that day
        fetch('/api/stats?period=today&date=' + currentDay)
            .then(r => r.json())
            .then(data => renderAppList(data))
            .catch(() => {});
    }
}

function loadData() {
    fetch('/api/stats?period=' + currentPeriod)
        .then(r => r.json())
        .then(data => {
            window.lastData = data;
            renderSummary(data);
            renderTimeline(data);
            renderAppList(data);
        })
        .catch(err => {
            document.getElementById('appList').innerHTML =
                '<div class="loading" style="color:#FF453A">加载失败，请检查服务是否运行</div>';
        });

    fetch('/api/advice')
        .then(r => r.json())
        .then(data => renderAdvice(data))
        .catch(() => {});
}

function renderSummary(data) {
    document.getElementById('totalTime').textContent = formatTime(data.total_seconds);
    document.getElementById('totalLabel').textContent =
        currentPeriod === 'today' ? '今日使用时长' :
        currentPeriod === 'week' ? '本周使用时长' : '本月使用时长';

    document.getElementById('appCount').textContent = data.apps.length;

    let notifTotal = 0;
    data.apps.forEach(a => notifTotal += a.notification_count);
    document.getElementById('notifCount').textContent = notifTotal;

    document.getElementById('topApp').textContent =
        data.apps.length > 0 ? getAppDisplayName(data.apps[0].name) : '--';
}

function renderTimeline(data) {
    const bars = document.getElementById('timelineBars');
    const labels = document.getElementById('timelineLabels');

    if (currentPeriod === 'today') {
        // 24 hour timeline
        let maxSec = 0;
        for (let h = 0; h < 24; h++) {
            if (data.hourly[h] && data.hourly[h] > maxSec) maxSec = data.hourly[h];
        }
        if (maxSec === 0) maxSec = 1;

        bars.innerHTML = '';
        for (let h = 0; h < 24; h++) {
            const sec = data.hourly[h] || 0;
            const height = Math.max(2, (sec / maxSec) * 100);
            const bar = document.createElement('div');
            bar.className = 'timeline-bar' + (h === currentHour ? ' active' : '');
            bar.dataset.hour = h;
            bar.style.height = height + '%';
            bar.title = h + ':00 - ' + formatTime(sec);
            bars.appendChild(bar);
        }

        labels.innerHTML = '';
        for (let h = 0; h <= 24; h += 3) {
            labels.innerHTML += '<span>' + h + ':00</span>';
        }
    } else {
        // Week/Month daily trend
        bars.className = 'daily-timeline';
        let maxSec = 0;
        const totals = data.daily_totals || {};
        Object.values(totals).forEach(v => { if (v > maxSec) maxSec = v; });
        if (maxSec === 0) maxSec = 1;

        bars.innerHTML = '';
        const dates = Object.keys(totals).sort();
        dates.forEach(date => {
            const sec = totals[date] || 0;
            const height = Math.max(2, (sec / maxSec) * 100);
            const bar = document.createElement('div');
            bar.className = 'daily-bar' + (date === currentDay ? ' active' : '');
            bar.dataset.day = date;
            bar.style.height = height + '%';
            bar.title = date + ': ' + formatTime(sec);
            bars.appendChild(bar);
        });

        labels.innerHTML = dates.map(d => {
            const parts = d.split('-');
            return '<span>' + parts[1] + '/' + parts[2] + '</span>';
        }).join('  ');
    }
}

function renderAppList(data) {
    let apps = data.apps || [];

    // Filter by selected hour
    if (currentPeriod === 'today' && currentHour >= 0) {
        // Re-fetch with hour filter
    }

    const container = document.getElementById('appList');

    if (apps.length === 0) {
        container.innerHTML = '<div class="loading">暂无数据</div>';
        return;
    }

    const totalSec = data.total_seconds || 1;

    let html = '';
    apps.forEach(app => {
        const pct = totalSec > 0 ? Math.round(app.total_seconds / totalSec * 100) : 0;
        const name = getAppDisplayName(app.name);
        html += '' +
        '<div class="app-item">' +
            '<div class="app-icon placeholder">' + getAppInitial(app.name) + '</div>' +
            '<div class="app-info">' +
                '<div class="app-name">' + name + '</div>' +
                '<div class="app-detail">' +
                    '前台 ' + formatTimeShort(app.foreground_seconds) +
                    ' · 后台 ' + formatTimeShort(app.background_seconds) +
                    ' · 打开 ' + app.open_count + '次' +
                '</div>' +
            '</div>' +
            '<div style="text-align:right">' +
                '<div class="app-time">' + formatTimeShort(app.total_seconds) + '</div>' +
                '<div style="font-size:11px;color:#8E8E93">' + pct + '%</div>' +
            '</div>' +
            (app.notification_count > 0 ?
                '<span class="app-badge badge-notif">' + app.notification_count + '通知</span>' : '') +
        '</div>';
    });

    container.innerHTML = html;
}

function renderAdvice(data) {
    const container = document.getElementById('adviceContent');
    if (!data.ready) {
        container.innerHTML = '<div class="advice-item">' +
            '<div class="advice-icon advice-info">!</div>' +
            '<div>' + data.message + '（已有' + data.days + '天数据）</div>' +
            '</div>';
        return;
    }
    if (!data.advice || data.advice.length === 0) {
        container.innerHTML = '<div class="advice-item">使用习惯良好，继续保持</div>';
        return;
    }
    container.innerHTML = data.advice.map(a =>
        '<div class="advice-item">' +
            '<div class="advice-icon advice-warn">!</div>' +
            '<div>' + a + '</div>' +
        '</div>'
    ).join('');
}

// Auto refresh
setInterval(loadData, 5000);

// Initial load
loadData();
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return HTML_TEMPLATE

def main():
    print(f"屏幕使用时间面板启动: http://127.0.0.1:19999")
    app.run(host='127.0.0.1', port=19999, debug=False)

if __name__ == '__main__':
    main()
