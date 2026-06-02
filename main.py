#!/usr/bin/env python3
"""
Windows桌面小工具：行情看板（A股 + 加密行情）
支持选项卡切换，系统托盘常驻，透明度调节
"""

import tkinter as tk
from tkinter import ttk
import threading
import os
import sys
import json
import pystray
from PIL import Image, ImageDraw
import win32event
import win32api
import winerror
from pynput import keyboard

from a_stock_tab import AStockFrame
from crypto_tab import CryptoFrame


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class MarketTicker:
    def __init__(self, root):
        self.root = root
        self.root.title("行情看板")
        
        self.config_file = os.path.join(get_app_dir(), 'config.json')
        self.config = self.load_config()
        
        self.alpha = self.config.get('alpha', 0.95)
        
        geometry = self.config.get('geometry', '350x450+100+100')
        self.root.geometry(geometry)
        self.root.resizable(True, True)
        
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', self.alpha)
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        self._drag_data = {"x": 0, "y": 0}
        
        self.create_widgets()
        self.create_tray_icon()
        
        self.setup_global_hotkey()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
        return {}
    
    def save_config(self):
        try:
            geometry = self.root.geometry()
            self.config['geometry'] = geometry
            self.config['alpha'] = self.alpha
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=8, pady=(8, 0))
        
        self.a_stock_tab = AStockFrame(self.notebook, self)
        self.crypto_tab = CryptoFrame(self.notebook, self)
        
        self.notebook.add(self.a_stock_tab, text="A股行情")
        self.notebook.add(self.crypto_tab, text="加密行情")
    
    def create_tray_icon(self):
        image = Image.new('RGB', (64, 64), color='#1a1a2e')
        draw = ImageDraw.Draw(image)
        draw.text((16, 16), "M", fill="#e94560")
        
        menu = pystray.Menu(
            pystray.MenuItem("显示/隐藏", self.toggle_window),
            pystray.MenuItem("透明度", pystray.Menu(
                pystray.MenuItem("95%", lambda: self.set_alpha(0.95)),
                pystray.MenuItem("80%", lambda: self.set_alpha(0.8)),
                pystray.MenuItem("60%", lambda: self.set_alpha(0.6)),
                pystray.MenuItem("40%", lambda: self.set_alpha(0.4)),
            )),
            pystray.MenuItem("退出", self.quit_application)
        )
        
        self.tray_icon = pystray.Icon("market_ticker", image, "行情看板", menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()
    
    def toggle_window(self):
        if self.root.state() == 'withdrawn':
            self.root.deiconify()
            self.root.state('normal')
        else:
            self.root.withdraw()
    
    def set_alpha(self, alpha):
        self.alpha = alpha
        windows = [self.root]
        if hasattr(self, 'a_stock_tab'):
            chart_window = getattr(self.a_stock_tab, 'chart_window', None)
            if chart_window is not None:
                windows.append(chart_window)
        for window in windows:
            try:
                if window and window.winfo_exists():
                    window.attributes('-alpha', alpha)
            except tk.TclError:
                pass

        alpha_var = getattr(getattr(self, 'a_stock_tab', None), 'alpha_var', None)
        if alpha_var is not None and abs(alpha_var.get() - alpha) > 0.001:
            alpha_var.set(alpha)
    
    
    def setup_global_hotkey(self):
        def on_press(key):
            if key == keyboard.Key.f12:
                self.root.after(0, self.toggle_window)
        
        self.hotkey_listener = keyboard.Listener(on_press=on_press)
        self.hotkey_listener.daemon = True
        self.hotkey_listener.start()
    
    def quit_application(self):
        self.save_config()
        self.a_stock_tab.running = False
        self.crypto_tab.running = False
        self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)
    
    def start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
    
    def do_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_data["x"])
        y = self.root.winfo_y() + (event.y - self._drag_data["y"])
        self.root.geometry(f"+{x}+{y}")
    
    def on_closing(self):
        self.save_config()
        self.root.withdraw()


def main():
    try:
        import requests
        import pystray
        from PIL import Image
        import matplotlib
    except ImportError as e:
        print(f"错误: 缺少依赖库 {e}")
        print("请运行: pip install -r requirements.txt")
        sys.exit(1)
    
    mutex_name = "MarketTicker_SingleInstance_Mutex"
    mutex = win32event.CreateMutex(None, False, mutex_name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox
        messagebox.showinfo("提示", "程序已经在运行中！")
        root.destroy()
        sys.exit(0)
    
    root = tk.Tk()
    app = MarketTicker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
