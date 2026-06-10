#!/usr/bin/env python3
"""
A股行情选项卡模块
支持添加/删除股票、实时行情更新、K线走势图显示
"""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import time
import threading
import queue
import os
import re
import sys
import matplotlib
matplotlib.use('TkAgg')
matplotlib.rcParams['font.sans-serif'] = [
    'Microsoft YaHei', 'SimHei', 'Microsoft JhengHei', 'SimSun', 'DejaVu Sans'
]
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.patheffects as pe
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter
import numpy as np


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class AStockFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        
        self.proxies = self.get_system_proxies()
        self.config_file = os.path.join(get_app_dir(), 'stocks.json')
        self.stocks = self.load_stocks()
        self.stock_data = {}
        
        self.data_sources = [
            {'name': '腾讯财经', 'fetch': self.fetch_from_tencent},
            {'name': '新浪财经', 'fetch': self.fetch_from_sina}
        ]
        
        self.selected_source = tk.StringVar(value="自动")
        self.source_names = ["自动"] + [s['name'] for s in self.data_sources]
        
        self.running = True
        self.active = False
        self.window_visible = True
        self.refresh_interval = 3.0
        self.background_refresh_interval = 30.0
        self.hidden_refresh_interval = 90.0
        self.update_lock = threading.Lock()
        self._refresh_now = threading.Event()
        self._drag_data = {"x": 0, "y": 0}
        self.chart_window = None
        self.chart_context = None
        self.chart_refresh_job = None
        self.chart_refresh_interval_ms = 10000
        self.chart_kline_refresh_interval_ms = 60000
        self.chart_refresh_queue = queue.Queue()
        
        self.create_widgets()
        
        self.update_thread = threading.Thread(target=self.update_prices, daemon=True)
        self.update_thread.start()
    
    def load_stocks(self):
        default_stocks = {
            "sh000001": "上证指数",
            "sz399001": "深证成指",
            "sz399006": "创业板指"
        }
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
        return default_stocks
    
    def save_stocks(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.stocks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def get_system_proxies(self):
        try:
            import urllib.request
            proxies = urllib.request.getproxies()
            filtered = {}
            for k, v in proxies.items():
                if v and k.lower() != 'no':
                    filtered[k] = v
            if filtered:
                return filtered
        except:
            pass
        
        proxies = {}
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        if http_proxy:
            proxies['http'] = http_proxy
        if https_proxy:
            proxies['https'] = https_proxy
        
        if not proxies:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if proxy_enable:
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if proxy_server:
                        if '=' in proxy_server:
                            for part in proxy_server.split(';'):
                                if part.startswith('http='):
                                    proxies['http'] = 'http://' + part[5:]
                                elif part.startswith('https='):
                                    proxies['https'] = 'https://' + part[6:]
                        else:
                            proxies['http'] = 'http://' + proxy_server
                            proxies['https'] = 'https://' + proxy_server
                winreg.CloseKey(key)
            except:
                pass
        
        return proxies if proxies else None
    
    def create_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        
        title_frame = ttk.Frame(self)
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        title_frame.columnconfigure(1, weight=1)
        
        ttk.Label(title_frame, text="A股行情", font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(title_frame, text="+ 添加股票", command=self.show_add_stock_dialog).grid(row=0, column=2, sticky=tk.E)
        
        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ('code', 'name', 'price', 'change_amount', 'change', 'turnover')
        self.stock_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        
        self.stock_tree.heading('code', text='代码')
        self.stock_tree.heading('name', text='名称')
        self.stock_tree.heading('price', text='现价')
        self.stock_tree.heading('change_amount', text='涨跌额')
        self.stock_tree.heading('change', text='涨跌幅')
        self.stock_tree.heading('turnover', text='换手')
        
        self.stock_tree.column('code', width=48, minwidth=48, anchor='center')
        self.stock_tree.column('name', width=66, minwidth=60, anchor='center')
        self.stock_tree.column('price', width=52, minwidth=50, anchor='e')
        self.stock_tree.column('change_amount', width=58, minwidth=54, anchor='e')
        self.stock_tree.column('change', width=58, minwidth=54, anchor='e')
        self.stock_tree.column('turnover', width=52, minwidth=48, anchor='e')
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.stock_tree.yview)
        self.stock_tree.configure(yscrollcommand=scrollbar.set)
        
        self.stock_tree.tag_configure('up', foreground='#E74C3C')
        self.stock_tree.tag_configure('down', foreground='#27AE60')
        self.stock_tree.tag_configure('flat', foreground='#666666')
        
        self.stock_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        self.stock_tree.bind('<Double-1>', self.on_stock_double_click)
        self.stock_tree.bind('<Button-3>', self.show_context_menu)
        
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="查看走势", command=self.show_stock_chart)
        self.context_menu.add_command(label="删除股票", command=self.delete_selected_stock)
        
        bottom_frame = ttk.Frame(self)
        bottom_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        bottom_frame.columnconfigure(1, weight=1)
        
        self.detail_visible = False
        self.detail_btn = ttk.Button(bottom_frame, text="▶ 设置", command=self.toggle_detail)
        self.detail_btn.grid(row=0, column=0, sticky=tk.W)
        
        refresh_btn = ttk.Button(bottom_frame, text="刷新", command=self.manual_refresh)
        refresh_btn.grid(row=0, column=2, sticky=tk.E, padx=(10, 0))
        
        self.detail_frame = ttk.Frame(self)
        self.detail_frame.columnconfigure(1, weight=1)
        
        ttk.Label(self.detail_frame, text="透明度:").grid(row=0, column=0, sticky=tk.W)
        self.alpha_var = tk.DoubleVar(value=self.app.alpha)
        alpha_scale = tk.Scale(self.detail_frame, from_=0.3, to=1.0, resolution=0.05,
                              variable=self.alpha_var, orient=tk.HORIZONTAL,
                              length=120, sliderlength=15,
                              command=lambda v: self.app.set_alpha(float(v)))
        alpha_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        
        ttk.Label(self.detail_frame, text="数据源:").grid(row=1, column=0, sticky=tk.W, pady=(3, 0))
        source_combo = ttk.Combobox(self.detail_frame, textvariable=self.selected_source, 
                                    values=self.source_names, state="readonly", width=10)
        source_combo.grid(row=1, column=1, sticky=tk.W, padx=(5, 0), pady=(3, 0))
        
        self.update_time_var = tk.StringVar(value="最后更新: --:--:--")
        ttk.Label(self.detail_frame, textvariable=self.update_time_var, 
                 font=('Arial', 8), foreground='gray').grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))
        
        ttk.Label(self.detail_frame, text="前台: 3秒",
                 font=('Arial', 8), foreground='gray').grid(row=3, column=2, sticky=tk.E, pady=(3, 0))
        
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.detail_frame, textvariable=self.status_var, 
                 font=('Arial', 8), foreground='gray').grid(row=4, column=0, columnspan=3, sticky=tk.W)
        
        self.refresh_stock_list()

    def set_refresh_active(self, active, visible=True):
        was_active = self.active
        self.active = bool(active)
        self.window_visible = bool(visible)
        if self.active and not was_active:
            self.request_refresh()

    def request_refresh(self):
        self._refresh_now.set()

    def _current_refresh_interval(self):
        if not self.window_visible:
            return self.hidden_refresh_interval
        if not self.active:
            return self.background_refresh_interval
        return self.refresh_interval

    def _wait_for_next_refresh(self, seconds):
        self._refresh_now.wait(max(0.05, seconds))
        self._refresh_now.clear()
    
    def toggle_detail(self):
        if self.detail_visible:
            self.detail_frame.grid_forget()
            self.detail_btn.configure(text="▶ 设置")
            self.detail_visible = False
        else:
            self.detail_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), padx=8, pady=(0, 8))
            self.detail_btn.configure(text="▼ 设置")
            self.detail_visible = True
    
    def show_add_stock_dialog(self):
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("添加股票")
        dialog.geometry("400x350")
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()
        
        dialog.update_idletasks()
        x = parent_x - 410
        y = parent_y
        if y + 350 > 900:
            y = 550
        if y < 0:
            y = 0
        dialog.geometry(f"+{x}+{y}")
        dialog.attributes('-alpha', self.app.alpha)
        
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        ttk.Label(dialog, text="输入股票代码或名称搜索:", font=('Microsoft YaHei', 10)).pack(pady=(15, 5))
        
        input_frame = ttk.Frame(dialog)
        input_frame.pack(fill=tk.X, padx=20)
        
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(input_frame, textvariable=self.search_var, width=30, font=('Arial', 11))
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.focus()
        
        ttk.Button(input_frame, text="搜索", command=self.search_stock, width=8).pack(side=tk.LEFT, padx=(5, 0))
        
        result_frame = ttk.Frame(dialog)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 5))
        
        self.result_listbox = tk.Listbox(result_frame, height=8, font=('Arial', 10))
        self.result_listbox.pack(fill=tk.BOTH, expand=True)
        self.result_listbox.bind('<Double-1>', lambda e: self.add_stock_from_list(dialog, keep_open=True))
        
        ttk.Label(dialog, text="双击列表项添加股票（可继续添加）", font=('Microsoft YaHei', 8), foreground='gray').pack(pady=(0, 5))
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        ttk.Button(btn_frame, text="添加选中", command=lambda: self.add_stock_from_list(dialog, keep_open=True), width=10).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy, width=10).pack(side=tk.RIGHT)
        
        search_entry.bind('<Return>', lambda e: self.search_stock())
        self.search_results = []
    
    def search_stock(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            return
        
        self.result_listbox.delete(0, tk.END)
        self.search_results = []
        
        try:
            url = f"https://smartbox.gtimg.cn/s3/?v=2&q={keyword}&t=all&c=1"
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, proxies=proxies, timeout=5)
            content = response.content.decode('gbk', errors='ignore')
            content = content.encode('utf-8').decode('unicode_escape', errors='ignore')
            
            match = re.search(r'v_hint="(.+)"', content)
            if match:
                stocks = match.group(1).split('^')
                for stock in stocks:
                    parts = stock.split('~')
                    if len(parts) >= 5:
                        market = parts[0]
                        code = parts[1]
                        name = parts[2]
                        stock_type = parts[4]
                        
                        if 'GP' in stock_type:
                            full_code = f"{market}{code}"
                            self.search_results.append((full_code, name))
                            self.result_listbox.insert(tk.END, f"{code} - {name}")
            
            if not self.search_results:
                self.result_listbox.insert(tk.END, "未找到匹配的股票")
                
        except Exception as e:
            self.result_listbox.insert(tk.END, f"搜索失败: {str(e)}")
    
    def add_stock_from_list(self, dialog, keep_open=False):
        selection = self.result_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一只股票", parent=dialog)
            return
        
        idx = selection[0]
        if idx < len(self.search_results):
            code, name = self.search_results[idx]
            if code in self.stocks:
                messagebox.showinfo("提示", f"{name} 已在列表中", parent=dialog)
            else:
                self.stocks[code] = name
                self.save_stocks()
                self.refresh_stock_list()
                self.status_var.set(f"已添加: {name}")
                if not keep_open:
                    dialog.destroy()
    
    def delete_selected_stock(self):
        selection = self.stock_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        code = self.stock_tree.item(item)['values'][0]
        
        full_code = None
        for c in self.stocks:
            if c.endswith(str(code)):
                full_code = c
                break
        
        if full_code and full_code in self.stocks:
            name = self.stocks[full_code]
            del self.stocks[full_code]
            self.save_stocks()
            self.refresh_stock_list()
            self.status_var.set(f"已删除: {name}")
    
    def show_context_menu(self, event):
        item = self.stock_tree.identify_row(event.y)
        if item:
            self.stock_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def on_stock_double_click(self, event):
        self.show_stock_chart()

    def _chart_palette(self):
        return {
            'bg': '#ffffff',
            'panel': '#fbfcff',
            'grid': '#edf1f7',
            'border': '#d8dee9',
            'axis': '#6b7280',
            'text': '#1f2937',
            'muted': '#8a94a6',
            'up': '#d94b4b',
            'down': '#19a26b',
            'price': '#246bfe',
            'avg': '#ffb000',
            'dif': '#2775d9',
            'dea': '#f28c28',
            'ma5': '#f5a623',
            'ma10': '#3769d8',
            'ma20': '#9b59b6',
            'zero': '#aab2c0',
        }

    def _clean_chart_text(self, value):
        try:
            return str(value).encode('gbk', errors='ignore').decode('gbk', errors='ignore')
        except Exception:
            return str(value)

    def _format_volume(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return '--'
        if value >= 100000000:
            return f'{value / 100000000:.2f}亿'
        if value >= 10000:
            return f'{value / 10000:.2f}万'
        return f'{value:.0f}'

    def _format_amount(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return '--'
        if value >= 100000000:
            return f'{value / 100000000:.2f}亿'
        if value >= 10000:
            return f'{value / 10000:.2f}万'
        return f'{value:.0f}'

    def _ema(self, values, period):
        if not values:
            return []
        multiplier = 2 / (period + 1)
        ema_values = [float(values[0])]
        for value in values[1:]:
            ema_values.append((float(value) - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    def _macd(self, prices):
        if len(prices) < 2:
            return [], [], []
        ema12 = self._ema(prices, 12)
        ema26 = self._ema(prices, 26)
        dif = [ema12[i] - ema26[i] for i in range(len(prices))]
        dea = self._ema(dif, 9)
        macd_bar = [2 * (dif[i] - dea[i]) for i in range(len(prices))]
        return dif, dea, macd_bar

    def _moving_average(self, values, window):
        if len(values) < window:
            return []
        values_array = np.asarray(values, dtype=float)
        result = np.full(len(values_array), np.nan)
        result[window - 1:] = np.convolve(values_array, np.ones(window) / window, mode='valid')
        return result

    def _intraday_average_prices(self, prices, avg_prices, volumes):
        price_array = np.asarray(prices, dtype=float)
        avg_array = np.asarray(avg_prices, dtype=float) if len(avg_prices) == len(prices) else np.array([])

        if len(avg_array) == len(price_array):
            min_valid_avg = max(0.01, float(np.nanmin(price_array)) * 0.75)
            max_valid_avg = float(np.nanmax(price_array)) * 1.25
            valid_mask = (
                np.isfinite(avg_array)
                & (avg_array >= min_valid_avg)
                & (avg_array <= max_valid_avg)
            )
            if valid_mask.sum() >= max(2, int(len(price_array) * 0.5)):
                valid_index = np.flatnonzero(valid_mask)
                return np.interp(np.arange(len(price_array)), valid_index, avg_array[valid_mask])

        volume_array = np.asarray(volumes, dtype=float) if len(volumes) == len(prices) else np.zeros(len(prices))
        volume_array = np.where(np.isfinite(volume_array) & (volume_array > 0), volume_array, 0)
        if volume_array.sum() > 0:
            cumulative_volume = np.cumsum(volume_array)
            cumulative_amount = np.cumsum(price_array * volume_array)
            return np.divide(
                cumulative_amount,
                cumulative_volume,
                out=np.cumsum(price_array) / np.arange(1, len(price_array) + 1),
                where=cumulative_volume > 0
            )

        return np.cumsum(price_array) / np.arange(1, len(price_array) + 1)

    def _style_chart_axis(self, ax, palette, hide_x=False):
        ax.set_facecolor(palette['panel'])
        ax.grid(True, color=palette['grid'], linewidth=0.8)
        ax.tick_params(axis='both', colors=palette['axis'], labelsize=8, length=0)
        if hide_x:
            ax.tick_params(labelbottom=False)
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.spines['left'].set_visible(False)
        for side in ('top', 'right', 'bottom'):
            ax.spines[side].set_color(palette['border'])
            ax.spines[side].set_linewidth(0.8)

    def _set_intraday_ticks(self, ax):
        ax.set_xticks([0, 60, 120, 180, 239])
        ax.set_xticklabels(['09:30', '10:30', '11:30/13:00', '14:00', '15:00'],
                           fontsize=8, color='#6b7280')

    def _format_intraday_time(self, value):
        text = str(value or '').strip()
        if ':' in text:
            return text[:5]
        digits = re.sub(r'\D', '', text)
        if len(digits) >= 4:
            return f'{digits[:2]}:{digits[2:4]}'
        return text or '--'

    def _get_crosshair_tooltip(self, frame, palette):
        tooltip = getattr(frame, '_crosshair_tooltip', None)
        if tooltip and tooltip.winfo_exists():
            return tooltip
        tooltip = tk.Label(
            frame,
            text='',
            justify=tk.LEFT,
            anchor=tk.W,
            bg='white',
            fg=palette['text'],
            bd=1,
            relief=tk.SOLID,
            padx=8,
            pady=5,
            font=('Microsoft YaHei', 8)
        )
        frame._crosshair_tooltip = tooltip
        return tooltip

    def _show_crosshair_tooltip(self, tooltip, event, text):
        tooltip.configure(text=text)
        tooltip.update_idletasks()
        parent_width = max(1, tooltip.master.winfo_width())
        parent_height = max(1, tooltip.master.winfo_height())
        width = tooltip.winfo_reqwidth()
        height = tooltip.winfo_reqheight()
        x = event.x + 14
        y = event.y + 14
        if x + width + 8 > parent_width:
            x = event.x - width - 14
        if y + height + 8 > parent_height:
            y = event.y - height - 14
        x = max(4, min(x, parent_width - width - 4))
        y = max(4, min(y, parent_height - height - 4))
        tooltip.place(x=x, y=y)
        tooltip.lift()

    def _hide_crosshair_tooltip(self, frame):
        tooltip = getattr(frame, '_crosshair_tooltip', None)
        if tooltip and tooltip.winfo_exists():
            tooltip.place_forget()

    def _disconnect_crosshair(self, canvas):
        for cid in getattr(canvas, '_crosshair_cids', []):
            try:
                canvas.mpl_disconnect(cid)
            except Exception:
                pass
        canvas._crosshair_cids = []

    def _setup_crosshair_blit(self, canvas, artists, use_axes_bbox=True):
        state = {'backgrounds': None, 'background': None}
        axes = []
        for artist in artists:
            if artist.axes and artist.axes not in axes:
                axes.append(artist.axes)
            artist.set_animated(True)

        if not axes:
            axes = list(canvas.figure.axes)

        def cache_background(event=None):
            try:
                if use_axes_bbox:
                    state['backgrounds'] = [
                        (ax, canvas.copy_from_bbox(ax.bbox))
                        for ax in axes
                    ]
                    state['background'] = None
                else:
                    state['background'] = canvas.copy_from_bbox(canvas.figure.bbox)
                    state['backgrounds'] = None
            except Exception:
                state['backgrounds'] = None
                state['background'] = None

        def render_hover():
            if use_axes_bbox and state['backgrounds'] is None:
                canvas.draw_idle()
                return
            if not use_axes_bbox and state['background'] is None:
                canvas.draw_idle()
                return
            try:
                if use_axes_bbox:
                    for ax, background in state['backgrounds']:
                        canvas.restore_region(background)
                else:
                    canvas.restore_region(state['background'])
                for artist in artists:
                    if artist.get_visible() and artist.axes:
                        artist.axes.draw_artist(artist)
                if use_axes_bbox:
                    for ax, _background in state['backgrounds']:
                        canvas.blit(ax.bbox)
                else:
                    canvas.blit(canvas.figure.bbox)
            except Exception:
                state['backgrounds'] = None
                state['background'] = None
                canvas.draw_idle()

        def clear_hover():
            if use_axes_bbox and state['backgrounds'] is None:
                canvas.draw_idle()
                return
            if not use_axes_bbox and state['background'] is None:
                canvas.draw_idle()
                return
            try:
                if use_axes_bbox:
                    for ax, background in state['backgrounds']:
                        canvas.restore_region(background)
                        canvas.blit(ax.bbox)
                else:
                    canvas.restore_region(state['background'])
                    canvas.blit(canvas.figure.bbox)
            except Exception:
                state['backgrounds'] = None
                state['background'] = None
                canvas.draw_idle()

        cid = canvas.mpl_connect('draw_event', cache_background)
        canvas.draw()
        cache_background()
        return render_hover, clear_hover, cid

    def _attach_intraday_crosshair(self, frame, axes, times, prices, average_array, volumes, palette, yesterday_close):
        canvas = getattr(frame, '_chart_canvas', None)
        if not canvas or not prices:
            return

        self._disconnect_crosshair(canvas)
        canvas.get_tk_widget().configure(cursor='crosshair')

        ax_price, ax_macd = axes
        dif, dea, macd_bar = self._macd(prices) if len(prices) >= 26 else ([], [], [])
        vlines = [
            ax.axvline(0, color='#243047', linewidth=1.05, linestyle='--', alpha=0.78, visible=False, zorder=20)
            for ax in axes
        ]
        hline = ax_price.axhline(0, color='#243047', linewidth=1.05, linestyle='--', alpha=0.78, visible=False, zorder=20)
        marker = ax_price.scatter([], [], s=42, color=palette['price'], edgecolor='white', linewidth=1.0, visible=False, zorder=21)
        tooltip = self._get_crosshair_tooltip(frame, palette)
        hover_state = {'idx': None, 'draw_at': 0.0, 'visible': False}
        hover_artists = vlines + [hline, marker]
        render_hover, clear_hover, draw_cid = self._setup_crosshair_blit(canvas, hover_artists, use_axes_bbox=False)

        def hide():
            if not hover_state['visible']:
                return
            hover_state['idx'] = None
            hover_state['visible'] = False
            for line in vlines:
                line.set_visible(False)
            hline.set_visible(False)
            marker.set_visible(False)
            self._hide_crosshair_tooltip(frame)
            clear_hover()

        def on_motion(event):
            if event.inaxes not in axes or event.xdata is None:
                hide()
                return

            idx = int(np.clip(round(event.xdata), 0, len(prices) - 1))
            if hover_state['visible'] and hover_state['idx'] == idx:
                return
            now = time.perf_counter()
            if hover_state['visible'] and now - hover_state['draw_at'] < 0.025:
                return
            hover_state['idx'] = idx
            hover_state['draw_at'] = now

            price = float(prices[idx])
            avg = float(average_array[idx]) if len(average_array) > idx else price
            if not np.isfinite(avg):
                avg = price
            time_label = self._format_intraday_time(times[idx] if idx < len(times) else idx)
            change_abs = price - yesterday_close
            change_pct = (change_abs / yesterday_close * 100) if yesterday_close else 0
            change_color = palette['up'] if change_abs >= 0 else palette['down']
            volume_value = volumes[idx] if idx < len(volumes) else 0
            detail_lines = [
                f'{time_label}',
                f'价格 {price:.2f}',
                f'涨跌 {change_abs:+.2f}  {change_pct:+.2f}%',
                f'均价 {avg:.2f}',
                f'成交量 {self._format_volume(volume_value)}手',
            ]
            if idx < len(macd_bar):
                detail_lines.append(f'MACD {macd_bar[idx]:+.3f}  DIF {dif[idx]:+.3f}  DEA {dea[idx]:+.3f}')

            for line in vlines:
                line.set_xdata([idx, idx])
                line.set_visible(True)
            hline.set_ydata([price, price])
            hline.set_visible(True)
            marker.set_offsets([[idx, price]])
            marker.set_facecolor(change_color)
            marker.set_visible(True)
            hover_state['visible'] = True
            self._show_crosshair_tooltip(tooltip, event, '\n'.join(detail_lines))
            render_hover()

        canvas._crosshair_cids = [
            draw_cid,
            canvas.mpl_connect('motion_notify_event', on_motion),
            canvas.mpl_connect('figure_leave_event', lambda event: hide()),
        ]

    def _attach_kline_crosshair(self, frame, axes, dates, opens, closes, highs, lows, volumes, amounts, palette):
        canvas = getattr(frame, '_chart_canvas', None)
        if not canvas or not dates:
            return

        self._disconnect_crosshair(canvas)
        canvas.get_tk_widget().configure(cursor='crosshair')

        ax_price, ax_volume, ax_macd = axes
        dif, dea, macd_bar = self._macd(closes) if len(closes) >= 26 else ([], [], [])
        vlines = [
            ax.axvline(0, color='#243047', linewidth=1.05, linestyle='--', alpha=0.78, visible=False, zorder=20)
            for ax in axes
        ]
        hline = ax_price.axhline(0, color='#243047', linewidth=1.05, linestyle='--', alpha=0.78, visible=False, zorder=20)
        marker = ax_price.scatter([], [], s=42, color=palette['text'], edgecolor='white', linewidth=1.0, visible=False, zorder=21)
        tooltip = self._get_crosshair_tooltip(frame, palette)
        hover_state = {'idx': None, 'draw_at': 0.0, 'visible': False}
        hover_artists = vlines + [hline, marker]
        render_hover, clear_hover, draw_cid = self._setup_crosshair_blit(canvas, hover_artists, use_axes_bbox=True)

        def hide():
            if not hover_state['visible']:
                return
            hover_state['idx'] = None
            hover_state['visible'] = False
            for line in vlines:
                line.set_visible(False)
            hline.set_visible(False)
            marker.set_visible(False)
            self._hide_crosshair_tooltip(frame)
            clear_hover()

        def on_motion(event):
            if event.inaxes not in axes or event.xdata is None:
                hide()
                return

            idx = int(np.clip(round(event.xdata), 0, len(dates) - 1))
            if hover_state['visible'] and hover_state['idx'] == idx:
                return
            now = time.perf_counter()
            if hover_state['visible'] and now - hover_state['draw_at'] < 0.025:
                return
            hover_state['idx'] = idx
            hover_state['draw_at'] = now

            previous_close = closes[idx - 1] if idx > 0 else opens[idx]
            change_abs = closes[idx] - previous_close
            change_pct = (change_abs / previous_close * 100) if previous_close else 0
            marker_color = palette['up'] if change_abs >= 0 else palette['down']
            detail_lines = [
                f'{dates[idx]}',
                f'开 {opens[idx]:.2f}  高 {highs[idx]:.2f}',
                f'低 {lows[idx]:.2f}  收 {closes[idx]:.2f}',
                f'涨跌 {change_abs:+.2f}  {change_pct:+.2f}%',
                f'额 {self._format_amount(amounts[idx])}  量 {self._format_volume(volumes[idx])}手',
            ]
            if idx < len(macd_bar):
                detail_lines.append(f'MACD {macd_bar[idx]:+.3f}  DIF {dif[idx]:+.3f}  DEA {dea[idx]:+.3f}')

            for line in vlines:
                line.set_xdata([idx, idx])
                line.set_visible(True)
            hline.set_ydata([closes[idx], closes[idx]])
            hline.set_visible(True)
            marker.set_offsets([[idx, closes[idx]]])
            marker.set_facecolor(marker_color)
            marker.set_edgecolor('white')
            marker.set_visible(True)
            hover_state['visible'] = True
            self._show_crosshair_tooltip(tooltip, event, '\n'.join(detail_lines))
            render_hover()

        canvas._crosshair_cids = [
            draw_cid,
            canvas.mpl_connect('motion_notify_event', on_motion),
            canvas.mpl_connect('figure_leave_event', lambda event: hide()),
        ]

    def _clear_frame(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def _get_chart_figure(self, frame, figsize):
        canvas = getattr(frame, '_chart_canvas', None)
        if canvas and canvas.get_tk_widget().winfo_exists():
            self._disconnect_crosshair(canvas)
            self._hide_crosshair_tooltip(frame)
            fig = canvas.figure
            fig.clear()
            fig.set_size_inches(figsize[0], figsize[1], forward=False)
            return fig, canvas
        fig = Figure(figsize=figsize, dpi=100)
        return fig, None

    def _draw_chart_figure(self, frame, fig, canvas):
        if canvas is None:
            for child in frame.winfo_children():
                child.destroy()
            canvas = FigureCanvasTkAgg(fig, master=frame)
            frame._chart_canvas = canvas
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        # Crosshair setup performs the immediate draw needed for blit background caching.

    def _show_chart_message(self, frame, text, font=('Microsoft YaHei', 12)):
        if frame.winfo_children():
            for child in frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(text=text)
                    return
            return
        ttk.Label(frame, text=text, font=font).pack(pady=50)

    def _cancel_chart_refresh(self):
        if self.chart_refresh_job and self.chart_window and self.chart_window.winfo_exists():
            try:
                self.chart_window.after_cancel(self.chart_refresh_job)
            except tk.TclError:
                pass
        if self.chart_context and self.chart_window and self.chart_window.winfo_exists():
            poll_job = self.chart_context.get('refresh_poll_job')
            if poll_job:
                try:
                    self.chart_window.after_cancel(poll_job)
                except tk.TclError:
                    pass
                self.chart_context['refresh_poll_job'] = None
        self.chart_refresh_job = None

    def _close_chart_window(self):
        self._cancel_chart_refresh()
        if self.chart_window and self.chart_window.winfo_exists():
            self.chart_window.destroy()
        self.chart_window = None
        self.chart_context = None

    def _schedule_chart_refresh(self):
        if not self.chart_context:
            return
        window = self.chart_context.get('window')
        if not window or not window.winfo_exists():
            self.chart_refresh_job = None
            return
        self.chart_refresh_job = window.after(self.chart_refresh_interval_ms, self._refresh_chart_window)

    def _refresh_chart_window(self):
        context = self.chart_context
        if not context:
            return
        window = context.get('window')
        if not window or not window.winfo_exists():
            self.chart_refresh_job = None
            return
        if context.get('refresh_in_progress'):
            self._schedule_chart_refresh()
            return

        context['refresh_count'] = context.get('refresh_count', 0) + 1
        now = time.monotonic()
        refresh_kline = (
            now - context.get('last_kline_refresh', 0)
        ) * 1000 >= self.chart_kline_refresh_interval_ms

        context['refresh_in_progress'] = True

        def fetch_in_background():
            try:
                realtime_data = self.fetch_realtime_data(context['full_code'])
                kline_data = self.fetch_kline_data(context['full_code']) if refresh_kline else None
            except Exception as e:
                print(f"刷新走势图失败: {e}")
                realtime_data = None
                kline_data = None
            self.chart_refresh_queue.put((context, realtime_data, kline_data, refresh_kline))

        threading.Thread(target=fetch_in_background, daemon=True).start()
        context['refresh_poll_job'] = window.after(100, self._poll_chart_refresh_queue)

    def _poll_chart_refresh_queue(self):
        context = self.chart_context
        if not context:
            return
        window = context.get('window')
        if not window or not window.winfo_exists():
            return

        processed_current = False
        while True:
            try:
                item = self.chart_refresh_queue.get_nowait()
            except queue.Empty:
                break
            item_context, realtime_data, kline_data, refresh_kline = item
            if item_context is context:
                processed_current = True
                self._apply_chart_refresh(context, realtime_data, kline_data, refresh_kline)

        if not processed_current and context.get('refresh_in_progress'):
            context['refresh_poll_job'] = window.after(100, self._poll_chart_refresh_queue)

    def _apply_chart_refresh(self, context, realtime_data, kline_data, refresh_kline):
        try:
            if context is not self.chart_context:
                return
            window = context.get('window')
            if not window or not window.winfo_exists():
                return

            realtime_signature = (
                len(realtime_data), tuple(realtime_data[-1])
            ) if realtime_data else None
            if realtime_signature and realtime_signature != context.get('last_realtime_signature'):
                self.draw_realtime_chart(
                    context['realtime_frame'],
                    context['full_code'],
                    context['name'],
                    realtime_data=realtime_data
                )
                context['last_realtime_signature'] = realtime_signature
            elif not realtime_signature:
                self._show_chart_message(context['realtime_frame'], "获取分时数据失败")

            if refresh_kline:
                kline_signature = (
                    len(kline_data), tuple(kline_data[-1])
                ) if kline_data else None
                if kline_signature and kline_signature != context.get('last_kline_signature'):
                    self.draw_stock_chart(
                        context['kline_frame'],
                        context['full_code'],
                        context['name'],
                        kline_data=kline_data
                    )
                    context['last_kline_signature'] = kline_signature
                elif not kline_signature:
                    self._show_chart_message(context['kline_frame'], "获取K线数据失败")
                context['last_kline_refresh'] = time.monotonic()
        finally:
            if context is self.chart_context:
                context['refresh_in_progress'] = False
                self._schedule_chart_refresh()

    def show_stock_chart(self):
        selection = self.stock_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        values = self.stock_tree.item(item)['values']
        code = values[0]
        name = values[1]
        
        full_code = None
        for c in self.stocks:
            if c.endswith(str(code)):
                full_code = c
                break
        
        if not full_code:
            return
        
        if self.chart_window is not None and self.chart_window.winfo_exists():
            self._close_chart_window()
        
        chart_window = tk.Toplevel(self.winfo_toplevel())
        chart_window.title(f"{name} ({code}) - 行情走势")
        window_width = 920
        window_height = 640
        screen_width = chart_window.winfo_screenwidth()
        screen_height = chart_window.winfo_screenheight()
        x = max(0, (screen_width - window_width) // 2)
        y = max(0, (screen_height - window_height) // 2 + 55)
        y = min(y, max(0, screen_height - window_height - 40))
        chart_window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        chart_window.minsize(760, 500)
        chart_window.configure(bg='#f3f6fb')
        chart_window.transient(self.winfo_toplevel())
        chart_window.attributes('-alpha', self.app.alpha)
        chart_window.protocol("WM_DELETE_WINDOW", self._close_chart_window)
        self.chart_window = chart_window
        
        notebook = ttk.Notebook(chart_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        realtime_frame = ttk.Frame(notebook)
        notebook.add(realtime_frame, text="分时走势 + MACD")
        
        kline_frame = ttk.Frame(notebook)
        notebook.add(kline_frame, text="日K线 + MACD")
        
        self.chart_context = {
            'window': chart_window,
            'realtime_frame': realtime_frame,
            'kline_frame': kline_frame,
            'full_code': full_code,
            'name': name,
            'refresh_count': 0,
            'refresh_in_progress': True,
            'last_kline_refresh': time.monotonic(),
        }
        self._show_chart_message(realtime_frame, "分时数据加载中...")
        self._show_chart_message(kline_frame, "K线数据加载中...")

        context = self.chart_context

        def fetch_initial_chart():
            try:
                realtime_data = self.fetch_realtime_data(full_code)
                kline_data = self.fetch_kline_data(full_code)
            except Exception as e:
                print(f"初始加载走势图失败: {e}")
                realtime_data = None
                kline_data = None
            self.chart_refresh_queue.put((context, realtime_data, kline_data, True))

        threading.Thread(target=fetch_initial_chart, daemon=True).start()
        context['refresh_poll_job'] = chart_window.after(100, self._poll_chart_refresh_queue)
    
    def draw_realtime_chart(self, window, full_code, name, realtime_data=None):
        try:
            if realtime_data is None:
                realtime_data = self.fetch_realtime_data(full_code)

            if not realtime_data:
                self._show_chart_message(window, "获取分时数据失败")
                return

            def safe_float(value, default=0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default

            palette = self._chart_palette()
            clean_name = self._clean_chart_text(name)
            times = []
            prices = []
            avg_prices = []
            volumes = []

            for item in realtime_data:
                if len(item) < 2:
                    continue
                price = safe_float(item[1], None)
                if price is None or not np.isfinite(price):
                    continue
                times.append(item[0])
                prices.append(price)

                if len(item) > 3:
                    avg_prices.append(safe_float(item[3], np.nan))
                else:
                    avg_prices.append(np.nan)

                if len(item) > 2:
                    volumes.append(safe_float(item[2], 0))
                else:
                    volumes.append(0)

            if not prices:
                self._show_chart_message(window, "分时数据为空")
                return

            total_points = 240
            prices = prices[:total_points]
            times = times[:len(prices)]
            avg_prices = avg_prices[:len(prices)]
            volumes = volumes[:len(prices)]
            x = np.arange(len(prices))
            average_array = self._intraday_average_prices(prices, avg_prices, volumes)
            average_price = float(average_array[-1]) if len(average_array) else prices[-1]
            chart_context = (
                self.chart_context
                if self.chart_context and self.chart_context.get('full_code') == full_code
                else None
            )

            snapshot = self.stock_data.get(full_code, {})
            yesterday_close = safe_float(snapshot.get('close'), prices[0])
            if yesterday_close <= 0:
                yesterday_close = prices[0]

            current_price = prices[-1]
            change_abs = current_price - yesterday_close
            change_pct = (change_abs / yesterday_close * 100) if yesterday_close else 0
            change_color = palette['up'] if change_abs >= 0 else palette['down']
            open_snapshot = safe_float(snapshot.get('open'), 0)
            high_snapshot = safe_float(snapshot.get('high'), 0)
            low_snapshot = safe_float(snapshot.get('low'), 0)
            volume_snapshot = safe_float(snapshot.get('volume'), 0)
            open_price = open_snapshot if open_snapshot > 0 else prices[0]
            high_price = max(max(prices), high_snapshot) if high_snapshot > 0 else max(prices)
            low_price = min(min(prices), low_snapshot) if low_snapshot > 0 else min(prices)
            volume_value = volume_snapshot if volume_snapshot > 0 else sum(volumes)

            fig, canvas = self._get_chart_figure(window, (9.0, 5.7))
            fig.patch.set_facecolor(palette['bg'])
            gs = fig.add_gridspec(2, 1, height_ratios=[3.3, 1.35], hspace=0.07)
            ax_price = fig.add_subplot(gs[0])
            ax_macd = fig.add_subplot(gs[1], sharex=ax_price)
            fig.subplots_adjust(left=0.055, right=0.94, top=0.815, bottom=0.09, hspace=0.06)

            updated_at = time.strftime('%H:%M:%S')
            fig.text(0.045, 0.965, f'{clean_name} ({full_code[2:]})  分时走势',
                     color=palette['text'], fontsize=12, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.77, 0.965, f'更新 {updated_at}   自动刷新 2秒',
                     color=palette['muted'], fontsize=8, ha='left',
                     fontname='Microsoft YaHei')
            fig.text(0.045, 0.880, f'{current_price:.2f}',
                     color=change_color, fontsize=21, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.900, f'{change_abs:+.2f}',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.862, f'{change_pct:+.2f}%',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.345, 0.905,
                     f'昨收 {yesterday_close:.2f}     今开 {open_price:.2f}     最高 {high_price:.2f}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')
            fig.text(0.345, 0.865,
                     f'最低 {low_price:.2f}     均价 {average_price:.2f}     成交量 {self._format_volume(volume_value)}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')

            self._style_chart_axis(ax_price, palette, hide_x=True)
            price_array = np.asarray(prices, dtype=float)
            ax_price.axhline(y=yesterday_close, color=palette['zero'],
                             linestyle='--', linewidth=0.8, alpha=0.85)

            ax_price.fill_between(x, price_array, yesterday_close,
                                  where=price_array >= yesterday_close,
                                  color=palette['up'], alpha=0.055, interpolate=True)
            ax_price.fill_between(x, price_array, yesterday_close,
                                  where=price_array < yesterday_close,
                                  color=palette['down'], alpha=0.055, interpolate=True)
            ax_price.plot(x, price_array, color=palette['price'], linewidth=1.35,
                          label='分时', zorder=4)
            if len(average_array):
                avg_line, = ax_price.plot(
                    x, average_array,
                    color=palette['avg'],
                    linewidth=2.1,
                    linestyle=(0, (5, 2)),
                    marker='o',
                    markersize=2.8,
                    markevery=max(1, len(x) // 16),
                    markerfacecolor=palette['avg'],
                    markeredgecolor='white',
                    markeredgewidth=0.8,
                    label='均价',
                    zorder=7,
                    solid_capstyle='round'
                )
                avg_line.set_path_effects([
                    pe.Stroke(linewidth=4.2, foreground='white', alpha=0.95),
                    pe.Normal()
                ])
                ax_price.annotate(
                    f'均 {average_price:.2f}',
                    xy=(x[-1], average_price),
                    xytext=(10, -14),
                    textcoords='offset points',
                    fontsize=8,
                    color=palette['avg'],
                    bbox=dict(boxstyle='round,pad=0.18', fc='white', ec=palette['avg'], lw=0.8),
                    clip_on=False,
                    zorder=8
                )
            ax_price.scatter([x[-1]], [current_price], s=18, color=change_color, zorder=4)
            ax_price.annotate(f'{current_price:.2f}', xy=(x[-1], current_price),
                              xytext=(8, 0), textcoords='offset points',
                              va='center', color=change_color, fontsize=8,
                              bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=change_color, lw=0.8),
                              clip_on=False)
            ax_price.legend(loc='upper left', fontsize=8, frameon=False, ncol=2)
            ax_price.set_xlim(0, total_points - 1)
            price_delta = max(abs(max(prices) - yesterday_close),
                              abs(min(prices) - yesterday_close),
                              yesterday_close * 0.002,
                              0.01)
            if chart_context is not None:
                price_delta = max(price_delta, chart_context.get('intraday_price_delta', 0))
                chart_context['intraday_price_delta'] = price_delta
            ax_price.set_ylim(yesterday_close - price_delta * 1.14,
                              yesterday_close + price_delta * 1.14)

            self._style_chart_axis(ax_macd, palette)
            ax_macd.axhline(y=0, color=palette['zero'], linewidth=0.8)
            if len(prices) >= 26:
                dif, dea, macd_bar = self._macd(prices)
                macd_x = np.arange(len(macd_bar))
                macd_colors = [palette['up'] if value >= 0 else palette['down'] for value in macd_bar]
                ax_macd.bar(macd_x, macd_bar, color=macd_colors, width=0.76, alpha=0.86, label='MACD')
                ax_macd.plot(macd_x, dif, color=palette['dif'], linewidth=1.0, label='DIF')
                ax_macd.plot(macd_x, dea, color=palette['dea'], linewidth=1.0, label='DEA')
                macd_limit = max(
                    max(abs(value) for value in macd_bar),
                    max(abs(value) for value in dif),
                    max(abs(value) for value in dea),
                    0.01
                )
                if chart_context is not None:
                    macd_limit = max(macd_limit, chart_context.get('intraday_macd_limit', 0))
                    chart_context['intraday_macd_limit'] = macd_limit
                ax_macd.set_ylim(-macd_limit * 1.25, macd_limit * 1.25)
                ax_macd.text(0.01, 0.9,
                             f'MACD {macd_bar[-1]:+.3f}   DIF {dif[-1]:+.3f}   DEA {dea[-1]:+.3f}',
                             transform=ax_macd.transAxes, color=palette['axis'],
                             fontsize=8, fontname='Microsoft YaHei')
                ax_macd.legend(loc='upper right', fontsize=8, frameon=False, ncol=3)
            else:
                ax_macd.text(0.5, 0.5, 'MACD 数据不足', ha='center', va='center',
                             color=palette['muted'], fontsize=9, transform=ax_macd.transAxes,
                             fontname='Microsoft YaHei')

            self._set_intraday_ticks(ax_macd)

            self._draw_chart_figure(window, fig, canvas)
            self._attach_intraday_crosshair(
                window,
                (ax_price, ax_macd),
                times,
                prices,
                average_array,
                volumes,
                palette,
                yesterday_close
            )

        except Exception as e:
            self._show_chart_message(window, f"绘制分时图失败: {str(e)}")
    
    def fetch_realtime_data(self, full_code):
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={full_code}"
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, proxies=proxies, timeout=10)
            content = response.text
            
            match = re.search(r'min_data=(.+)', content, re.DOTALL)
            if match:
                json_str = match.group(1).strip().rstrip(';')
                data = json.loads(json_str)
                
                if 'data' in data and full_code in data['data']:
                    stock_data = data['data'][full_code]
                    if 'data' in stock_data and 'data' in stock_data['data']:
                        mins = stock_data['data']['data']
                        result = []
                        for item in mins:
                            parts = item.split()
                            if len(parts) >= 4:
                                time_str = parts[0]
                                price = parts[1]
                                volume = parts[2]
                                avg_price = price
                                try:
                                    volume_value = float(volume)
                                    amount_value = float(parts[3])
                                    if volume_value > 0 and amount_value > 0:
                                        avg_price = amount_value / (volume_value * 100)
                                except (TypeError, ValueError):
                                    pass
                                result.append([time_str, price, volume, avg_price])
                        return result
            
            url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_tick_data=/CN_MarketDataService.getDataService?symbol={full_code}&datalen=240"
            headers = {'Referer': 'https://finance.sina.com.cn'}
            
            response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
            content = response.text
            
            match = re.search(r'\[(.+)\]', content, re.DOTALL)
            if match:
                json_str = '[' + match.group(1) + ']'
                data = json.loads(json_str)
                result = []
                for item in data:
                    if 'ticktime' in item and 'price' in item and 'volume' in item:
                        result.append([
                            item['ticktime'],
                            item['price'],
                            item['volume'],
                            item.get('avg_price', item['price'])
                        ])
                return result
            
        except Exception as e:
            print(f"获取分时数据失败: {e}")
        
        return None
    
    def draw_stock_chart(self, window, full_code, name, kline_data=None):
        try:
            if kline_data is None:
                kline_data = self.fetch_kline_data(full_code)
            
            if not kline_data:
                self._show_chart_message(window, "获取K线数据失败")
                return

            palette = self._chart_palette()
            clean_name = self._clean_chart_text(name)
            dates = []
            opens = []
            closes = []
            highs = []
            lows = []
            volumes = []
            amounts = []

            for item in kline_data:
                try:
                    dates.append(item[0])
                    open_price = float(item[1])
                    close_price = float(item[2])
                    high_price = float(item[3])
                    low_price = float(item[4])
                    volume = float(item[5])
                    if len(item) > 6 and item[6] not in (None, ''):
                        amount = float(item[6])
                    else:
                        amount = ((open_price + close_price) / 2) * volume

                    opens.append(open_price)
                    closes.append(close_price)
                    highs.append(high_price)
                    lows.append(low_price)
                    volumes.append(volume)
                    amounts.append(amount)
                except (IndexError, TypeError, ValueError):
                    continue

            if not dates:
                self._show_chart_message(window, "K线数据为空")
                return

            x = np.arange(len(dates))
            candle_colors = [palette['up'] if close_price >= open_price else palette['down']
                             for open_price, close_price in zip(opens, closes)]
            amount_colors = []
            for i, close_price in enumerate(closes):
                reference = closes[i - 1] if i > 0 else opens[i]
                amount_colors.append(palette['up'] if close_price >= reference else palette['down'])
            bar_width = 0.62

            previous_close = closes[-2] if len(closes) > 1 else opens[-1]
            change_abs = closes[-1] - previous_close
            change_pct = (change_abs / previous_close * 100) if previous_close else 0
            change_color = palette['up'] if change_abs >= 0 else palette['down']

            fig, canvas = self._get_chart_figure(window, (9.0, 5.7))
            fig.patch.set_facecolor(palette['bg'])
            gs = fig.add_gridspec(3, 1, height_ratios=[3.2, 1.0, 1.35], hspace=0.06)
            ax_price = fig.add_subplot(gs[0])
            ax_volume = fig.add_subplot(gs[1], sharex=ax_price)
            ax_macd = fig.add_subplot(gs[2], sharex=ax_price)
            fig.subplots_adjust(left=0.055, right=0.94, top=0.815, bottom=0.09, hspace=0.06)

            updated_at = time.strftime('%H:%M:%S')
            fig.text(0.045, 0.965, f'{clean_name} ({full_code[2:]})  日K走势',
                     color=palette['text'], fontsize=12, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.77, 0.965, f'更新 {updated_at}   日K每15秒刷新',
                     color=palette['muted'], fontsize=8, ha='left',
                     fontname='Microsoft YaHei')
            fig.text(0.045, 0.880, f'{closes[-1]:.2f}',
                     color=change_color, fontsize=21, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.900, f'{change_abs:+.2f}',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.862, f'{change_pct:+.2f}%',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.345, 0.905,
                     f'开 {opens[-1]:.2f}     高 {highs[-1]:.2f}     低 {lows[-1]:.2f}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')
            fig.text(0.345, 0.865,
                     f'额 {self._format_amount(amounts[-1])}     量 {self._format_volume(volumes[-1])}手     日期 {dates[-1]}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')

            self._style_chart_axis(ax_price, palette, hide_x=True)
            price_span = max(highs) - min(lows)
            min_body = max(price_span * 0.002, 0.01)
            for i in range(len(dates)):
                ax_price.vlines(x[i], lows[i], highs[i], color=candle_colors[i], linewidth=1.0)
                bottom = min(opens[i], closes[i])
                height = abs(closes[i] - opens[i])
                if height < min_body:
                    height = min_body
                    bottom = closes[i] - height / 2
                ax_price.bar(x[i], height, bottom=bottom, width=bar_width,
                             color=candle_colors[i], edgecolor=candle_colors[i], linewidth=0.8)

            ma_specs = [
                (5, palette['ma5'], 'MA5'),
                (10, palette['ma10'], 'MA10'),
                (20, palette['ma20'], 'MA20'),
            ]
            for period, color, label in ma_specs:
                ma_values = self._moving_average(closes, period)
                if len(ma_values):
                    ax_price.plot(x, ma_values, color=color, linewidth=1.0, label=label)

            if price_span <= 0:
                price_span = max(closes[-1] * 0.02, 0.02)
            ax_price.set_ylim(min(lows) - price_span * 0.08, max(highs) + price_span * 0.08)
            ax_price.set_xlim(-1, len(dates))
            ax_price.legend(loc='upper left', fontsize=8, frameon=False, ncol=4)

            self._style_chart_axis(ax_volume, palette, hide_x=True)
            ax_volume.bar(x, amounts, color=amount_colors, width=bar_width, alpha=0.72)
            amount_max = max(amounts) if amounts else 0
            ax_volume.set_ylim(0, amount_max * 1.25 if amount_max > 0 else 1)
            ax_volume.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: self._format_amount(value)))
            ax_volume.yaxis.offsetText.set_visible(False)
            ax_volume.text(0.01, 0.78, f'成交额 {self._format_amount(amounts[-1])}',
                           transform=ax_volume.transAxes, color=palette['axis'],
                           fontsize=8, fontname='Microsoft YaHei')

            self._style_chart_axis(ax_macd, palette)
            ax_macd.axhline(y=0, color=palette['zero'], linewidth=0.8)
            if len(closes) >= 26:
                dif, dea, macd_bar = self._macd(closes)
                macd_colors = [palette['up'] if value >= 0 else palette['down'] for value in macd_bar]
                ax_macd.bar(x, macd_bar, color=macd_colors, width=bar_width, alpha=0.86, label='MACD')
                ax_macd.plot(x, dif, color=palette['dif'], linewidth=1.0, label='DIF')
                ax_macd.plot(x, dea, color=palette['dea'], linewidth=1.0, label='DEA')
                macd_limit = max(
                    max(abs(value) for value in macd_bar),
                    max(abs(value) for value in dif),
                    max(abs(value) for value in dea),
                    0.01
                )
                ax_macd.set_ylim(-macd_limit * 1.25, macd_limit * 1.25)
                ax_macd.text(0.01, 0.9,
                             f'MACD {macd_bar[-1]:+.3f}   DIF {dif[-1]:+.3f}   DEA {dea[-1]:+.3f}',
                             transform=ax_macd.transAxes, color=palette['axis'],
                             fontsize=8, fontname='Microsoft YaHei')
                ax_macd.legend(loc='upper right', fontsize=8, frameon=False, ncol=3)
            else:
                ax_macd.text(0.5, 0.5, 'MACD 数据不足', ha='center', va='center',
                             color=palette['muted'], fontsize=9, transform=ax_macd.transAxes,
                             fontname='Microsoft YaHei')

            if len(dates) > 1:
                tick_count = min(9, len(dates))
                tick_positions = sorted(set(np.linspace(0, len(dates) - 1, tick_count, dtype=int).tolist()))
            else:
                tick_positions = [0]
            short_dates = [dates[i][5:] if len(dates[i]) > 5 else dates[i] for i in tick_positions]
            ax_macd.set_xticks(tick_positions)
            ax_macd.set_xticklabels(short_dates, rotation=0, fontsize=8, color=palette['axis'])
            
            self._draw_chart_figure(window, fig, canvas)
            self._attach_kline_crosshair(
                window,
                (ax_price, ax_volume, ax_macd),
                dates,
                opens,
                closes,
                highs,
                lows,
                volumes,
                amounts,
                palette
            )
            
        except Exception as e:
            self._show_chart_message(window, f"绘制走势图失败: {str(e)}")
    
    def fetch_kline_data(self, full_code):
        try:
            code = full_code[2:]
            market = full_code[:2]

            try:
                secid_market = '1' if market == 'sh' else '0'
                params = {
                    'secid': f'{secid_market}.{code}',
                    'fields1': 'f1,f2,f3,f4,f5,f6',
                    'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                    'klt': '101',
                    'fqt': '1',
                    'end': '20500101',
                    'lmt': '60'
                }
                headers = {
                    'Referer': 'https://quote.eastmoney.com/',
                    'User-Agent': 'Mozilla/5.0'
                }
                hosts = [
                    'push2his.eastmoney.com',
                    '1.push2his.eastmoney.com',
                    '3.push2his.eastmoney.com',
                    '4.push2his.eastmoney.com',
                    '5.push2his.eastmoney.com',
                ]
                last_error = None
                for host in hosts:
                    try:
                        eastmoney_url = f'https://{host}/api/qt/stock/kline/get'
                        response = requests.get(eastmoney_url, params=params, headers=headers, timeout=6)
                        data = response.json()
                        klines = data.get('data', {}).get('klines') if isinstance(data, dict) else None
                        if klines:
                            result = []
                            for row in klines:
                                parts = row.split(',')
                                if len(parts) >= 7:
                                    result.append([
                                        parts[0],
                                        parts[1],
                                        parts[2],
                                        parts[3],
                                        parts[4],
                                        parts[5],
                                        parts[6]
                                    ])
                            if result:
                                return result
                    except Exception as e:
                        last_error = e
                if last_error:
                    print(f"从东方财富获取K线数据失败: {last_error}")
            except Exception as e:
                print(f"从东方财富获取K线数据失败: {e}")

            try:
                tencent_url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
                params = {'param': f'{market}{code},day,,,60,qfq'}
                response = requests.get(tencent_url, params=params, timeout=10)
                data = response.json()
                stock_data = data.get('data', {}).get(f'{market}{code}', {}) if isinstance(data, dict) else {}
                klines = stock_data.get('qfqday') or stock_data.get('day')
                if klines:
                    result = []
                    for row in klines:
                        if len(row) >= 6:
                            open_price = float(row[1])
                            close_price = float(row[2])
                            volume_hands = float(row[5])
                            amount = ((open_price + close_price) / 2) * volume_hands * 100
                            result.append([
                                row[0],
                                row[1],
                                row[2],
                                row[3],
                                row[4],
                                row[5],
                                amount
                            ])
                    if result:
                        return result
            except Exception as e:
                print(f"从腾讯获取K线数据失败: {e}")
            
            url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData?symbol={market}{code}&scale=240&ma=no&datalen=60"
            
            headers = {'Referer': 'https://finance.sina.com.cn'}
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
            content = response.text
            
            match = re.search(r'\[(.+)\]', content, re.DOTALL)
            if match:
                json_str = '[' + match.group(1) + ']'
                data = json.loads(json_str)
                result = []
                for item in data:
                    result.append([
                        item['day'],
                        item['open'],
                        item['close'],
                        item['high'],
                        item['low'],
                        item['volume']
                    ])
                return result
            
        except Exception as e:
            print(f"获取K线数据失败: {e}")
        
        return None
    
    def fetch_from_sina(self, stock_codes):
        result = {}
        
        try:
            codes = list(stock_codes)
            url = f"https://hq.sinajs.cn/list={','.join(codes)}"
            headers = {'Referer': 'https://finance.sina.com.cn'}
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, headers=headers, proxies=proxies, timeout=5)
            content = response.text
            
            lines = content.strip().split('\n')
            for line in lines:
                match = re.search(r'hq_str_(\w+)="(.+)"', line)
                if match:
                    code = match.group(1)
                    data = match.group(2).split(',')
                    
                    if len(data) >= 32:
                        name = data[0]
                        open_price = float(data[1]) if data[1] else 0
                        close_price = float(data[2]) if data[2] else 0
                        current_price = float(data[3]) if data[3] else 0
                        high_price = float(data[4]) if data[4] else 0
                        low_price = float(data[5]) if data[5] else 0
                        volume = float(data[8]) if data[8] else 0
                        amount = float(data[9]) if data[9] else 0
                        
                        if close_price > 0 and current_price > 0:
                            change_amount = current_price - close_price
                            change = ((current_price - close_price) / close_price) * 100
                        else:
                            change_amount = 0
                            change = 0
                        
                        result[code] = {
                            'name': name,
                            'code': code,
                            'price': current_price,
                            'change_amount': change_amount,
                            'open': open_price,
                            'close': close_price,
                            'high': high_price,
                            'low': low_price,
                            'volume': volume,
                            'amount': amount,
                            'change': change,
                            'turnover': None
                        }
            
        except Exception as e:
            print(f"从新浪获取行情失败: {e}")
        
        return result
    
    def fetch_from_tencent(self, stock_codes):
        result = {}
        
        try:
            codes = list(stock_codes)
            url = f"https://qt.gtimg.cn/q={','.join(codes)}"
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, proxies=proxies, timeout=5)
            content = response.text
            
            lines = content.strip().split('\n')
            for line in lines:
                match = re.search(r'v_(\w+)="(.+)"', line)
                if match:
                    code = match.group(1)
                    data = match.group(2).split('~')
                    
                    if len(data) >= 45:
                        name = data[1]
                        current_price = float(data[3]) if data[3] else 0
                        close_price = float(data[4]) if data[4] else 0
                        open_price = float(data[5]) if data[5] else 0
                        volume = float(data[6]) if data[6] else 0
                        high_price = float(data[33]) if data[33] else 0
                        low_price = float(data[34]) if data[34] else 0
                        change_amount = float(data[31]) if data[31] else 0
                        change = float(data[32]) if data[32] else 0
                        amount = float(data[37]) * 10000 if len(data) > 37 and data[37] else 0
                        turnover = float(data[38]) if len(data) > 38 and data[38] else None
                        
                        result[code] = {
                            'name': name,
                            'code': code,
                            'price': current_price,
                            'change_amount': change_amount,
                            'open': open_price,
                            'close': close_price,
                            'high': high_price,
                            'low': low_price,
                            'volume': volume,
                            'amount': amount,
                            'change': change,
                            'turnover': turnover
                        }
            
        except Exception as e:
            print(f"从腾讯获取行情失败: {e}")
        
        return result
    
    def fetch_price(self, stock_codes):
        selected = self.selected_source.get()
        
        if selected != "自动":
            for source in self.data_sources:
                if source['name'] == selected:
                    data = source['fetch'](stock_codes)
                    if data:
                        return data
        
        for source in self.data_sources:
            data = source['fetch'](stock_codes)
            if data:
                return data
        
        return {}
    
    def refresh_stock_list(self):
        for item in self.stock_tree.get_children():
            self.stock_tree.delete(item)
        
        for code, name in self.stocks.items():
            clean_name = name.encode('gbk', errors='ignore').decode('gbk', errors='ignore')
            
            if code in self.stock_data:
                data = self.stock_data[code]
                price = f"{data['price']:.2f}"
                change = data['change']
                change_str = f"{change:+.2f}%"
                change_amount = data.get('change_amount')
                if change_amount is None:
                    close_price = data.get('close', 0)
                    current_price = data.get('price', 0)
                    change_amount = current_price - close_price if close_price and current_price else 0
                change_amount_str = f"{change_amount:+.2f}"
                turnover = data.get('turnover')
                turnover_str = f"{turnover:.2f}%" if turnover is not None else "--"
                
                if change > 0:
                    tag = 'up'
                elif change < 0:
                    tag = 'down'
                else:
                    tag = 'flat'
                
                self.stock_tree.insert(
                    '',
                    'end',
                    values=(code[2:], clean_name, price, change_amount_str, change_str, turnover_str),
                    tags=(tag,)
                )
            else:
                self.stock_tree.insert('', 'end', values=(code[2:], clean_name, "--", "--", "--", "--"), tags=('flat',))
    
    def update_prices(self):
        while self.running:
            if not self.active or not self.window_visible:
                self._wait_for_next_refresh(1.0)
                continue

            cycle_started = time.monotonic()
            acquired = self.update_lock.acquire(blocking=False)
            if not acquired:
                self._wait_for_next_refresh(self._current_refresh_interval())
                continue

            try:
                if self.stocks:
                    stock_codes = list(self.stocks.keys())
                    data = self.fetch_price(stock_codes)
                    
                    if data:
                        self.stock_data.update(data)
                        self.after(0, self.refresh_stock_list)
                        
                        current_time = time.strftime("%H:%M:%S")
                        self.after(0, lambda: self.update_time_var.set(f"最后更新: {current_time}"))
                        self.after(0, lambda: self.status_var.set("数据更新成功"))
                    
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"更新错误: {str(e)}"))
            finally:
                self.update_lock.release()

            elapsed = time.monotonic() - cycle_started
            self._wait_for_next_refresh(self._current_refresh_interval() - elapsed)
    
    def manual_refresh(self):
        self.status_var.set("正在刷新...")
        threading.Thread(target=self._manual_refresh_thread, daemon=True).start()
    
    def _manual_refresh_thread(self):
        acquired = self.update_lock.acquire(blocking=False)
        if not acquired:
            self.after(0, lambda: self.status_var.set("刷新中，请稍候"))
            return

        try:
            if self.stocks:
                stock_codes = list(self.stocks.keys())
                data = self.fetch_price(stock_codes)
                
                if data:
                    self.stock_data.update(data)
                    self.after(0, self.refresh_stock_list)
                    
                    current_time = time.strftime("%H:%M:%S")
                    self.after(0, lambda: self.update_time_var.set(f"最后更新: {current_time}"))
                    self.after(0, lambda: self.status_var.set("手动刷新完成"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"刷新失败: {str(e)}"))
        finally:
            self.update_lock.release()
