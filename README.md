# ScreenTimeTracker · 屏幕使用时间

Windows 上的「屏幕使用时间」：后台采集当前活动窗口，统计每个应用今天用了多久，再用一个本地 Web 面板以 iOS 风格展示。

## 组成

| 文件 | 作用 |
| --- | --- |
| `tracker.py` | 后台采集：活动窗口、空闲时间、通知，写入 SQLite |
| `server.py` | Flask 面板，端口 19999，前端全部内嵌 |
| `panel.bat` | 一键启动面板并打开浏览器 |
| `start.bat` | 启动后台采集 |

## 运行

```bat
start.bat     :: 开始采集
panel.bat     :: 打开面板 http://127.0.0.1:19999
```

依赖：Python 3.10+，`pip install flask`。数据只保存在本机 `screentime.db`。

## License

MIT
