#!/usr/bin/env python3
"""
美股行情页签：支持美股、ETF 与黄金期货的添加、删除、实时行情和走势图。
"""

import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('TkAgg')
matplotlib.rcParams['font.sans-serif'] = [
    'Microsoft YaHei', 'SimHei', 'Microsoft JhengHei', 'SimSun', 'DejaVu Sans'
]
matplotlib.rcParams['axes.unicode_minus'] = False
import numpy as np
import requests
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from tkinter import messagebox, ttk


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class USStockFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        self.proxies = self.get_system_proxies()
        self.config_file = os.path.join(get_app_dir(), 'us_stocks.json')
        self.us_stocks = self.load_us_stocks()
        self.stock_data = {}

        self.selected_source = tk.StringVar(value="自动")
        self.source_names = ["自动", "Alpaca夜盘", "Nasdaq/新浪", "CNBC备用"]
        self._alpaca_missing_credentials_logged = False

        self.running = True
        self.active = False
        self.window_visible = True
        self.refresh_interval = 5.0
        self.background_refresh_interval = 45.0
        self.hidden_refresh_interval = 120.0
        self.request_timeout = 5.0
        self.update_lock = threading.Lock()
        self._refresh_now = threading.Event()

        self.chart_window = None
        self.chart_context = None
        self.chart_refresh_job = None
        self.chart_refresh_interval_ms = 20000
        self.chart_kline_refresh_interval_ms = 60000
        self.chart_refresh_queue = queue.Queue()

        self.create_widgets()

        self.update_thread = threading.Thread(target=self.update_prices, daemon=True)
        self.update_thread.start()

    def load_us_stocks(self):
        default_stocks = {
            "AAPL": {"name": "Apple", "asset": "STOCKS", "source": "nasdaq"},
            "NVDA": {"name": "NVIDIA", "asset": "STOCKS", "source": "nasdaq"},
            "TSLA": {"name": "Tesla", "asset": "STOCKS", "source": "nasdaq"},
            "SPY": {"name": "SPDR S&P 500 ETF", "asset": "ETF", "source": "nasdaq"},
            "QQQ": {"name": "Invesco QQQ Trust", "asset": "ETF", "source": "nasdaq"},
            "GLD": {"name": "SPDR Gold Shares", "asset": "ETF", "source": "nasdaq"},
            "hf_GC": {"name": "纽约黄金", "asset": "FUTURES", "source": "sina", "chart_symbol": "GC"},
        }
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                return {
                    str(symbol).upper() if not str(symbol).startswith('hf_') else str(symbol): self._normalize_item(symbol, item)
                    for symbol, item in loaded.items()
                }
        except Exception as e:
            print(f"加载美股配置文件失败: {e}")
        return default_stocks

    def _normalize_item(self, symbol, item):
        if isinstance(item, dict):
            name = item.get('name') or item.get('title') or str(symbol)
            asset = str(item.get('asset') or item.get('type') or 'STOCKS').upper()
            source = str(item.get('source') or ('sina' if str(symbol).startswith('hf_') else 'nasdaq')).lower()
            normalized = {
                'name': name,
                'asset': 'ETF' if asset in ('ETF', 'ETFS') else ('FUTURES' if asset in ('FUTURE', 'FUTURES', 'COMMODITY') else 'STOCKS'),
                'source': source,
            }
            if item.get('chart_symbol'):
                normalized['chart_symbol'] = item.get('chart_symbol')
            return normalized
        return {
            'name': str(item),
            'asset': 'FUTURES' if str(symbol).startswith('hf_') else 'STOCKS',
            'source': 'sina' if str(symbol).startswith('hf_') else 'nasdaq',
        }

    def save_us_stocks(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.us_stocks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存美股配置文件失败: {e}")

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
        except Exception:
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
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
                )
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
            except Exception:
                pass

        return proxies if proxies else None

    def create_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        title_frame = ttk.Frame(self)
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        title_frame.columnconfigure(1, weight=1)

        ttk.Label(title_frame, text="美股行情", font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(title_frame, text="+ 添加标的", command=self.show_add_us_stock_dialog).grid(row=0, column=2, sticky=tk.E)

        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ('symbol', 'name', 'price', 'change_amount', 'change', 'session')
        self.us_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)

        self.us_tree.heading('symbol', text='代码')
        self.us_tree.heading('name', text='名称')
        self.us_tree.heading('price', text='现价')
        self.us_tree.heading('change_amount', text='涨跌额')
        self.us_tree.heading('change', text='涨跌幅')
        self.us_tree.heading('session', text='时段')

        self.us_tree.column('symbol', width=58, minwidth=52, anchor='center')
        self.us_tree.column('name', width=82, minwidth=68, anchor='center')
        self.us_tree.column('price', width=68, minwidth=58, anchor='e')
        self.us_tree.column('change_amount', width=62, minwidth=56, anchor='e')
        self.us_tree.column('change', width=60, minwidth=54, anchor='e')
        self.us_tree.column('session', width=58, minwidth=52, anchor='center')

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.us_tree.yview)
        self.us_tree.configure(yscrollcommand=scrollbar.set)

        self.us_tree.tag_configure('up', foreground='#E74C3C')
        self.us_tree.tag_configure('down', foreground='#27AE60')
        self.us_tree.tag_configure('flat', foreground='#666666')

        self.us_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.us_tree.bind('<Double-1>', self.on_stock_double_click)
        self.us_tree.bind('<Button-3>', self.show_context_menu)

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="查看走势", command=self.show_stock_chart)
        self.context_menu.add_command(label="删除标的", command=self.delete_selected_stock)

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

        ttk.Label(self.detail_frame, text="透明度").grid(row=0, column=0, sticky=tk.W)
        self.alpha_var = tk.DoubleVar(value=self.app.alpha)
        alpha_scale = tk.Scale(
            self.detail_frame,
            from_=0.3,
            to=1.0,
            resolution=0.05,
            variable=self.alpha_var,
            orient=tk.HORIZONTAL,
            length=120,
            sliderlength=15,
            command=lambda v: self.app.set_alpha(float(v))
        )
        alpha_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0))

        ttk.Label(self.detail_frame, text="数据源").grid(row=1, column=0, sticky=tk.W, pady=(3, 0))
        source_combo = ttk.Combobox(
            self.detail_frame,
            textvariable=self.selected_source,
            values=self.source_names,
            state="readonly",
            width=12
        )
        source_combo.grid(row=1, column=1, sticky=tk.W, padx=(5, 0), pady=(3, 0))
        source_combo.bind("<<ComboboxSelected>>", self.on_source_change)

        self.update_time_var = tk.StringVar(value="最后更新: --:--:--")
        ttk.Label(
            self.detail_frame,
            textvariable=self.update_time_var,
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        ttk.Label(
            self.detail_frame,
            text="前台: 5秒",
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=3, column=2, sticky=tk.E, pady=(3, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            self.detail_frame,
            textvariable=self.status_var,
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)

        self.refresh_us_list()

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

    def show_add_us_stock_dialog(self):
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("添加美股/ETF/黄金")
        dialog.geometry("430x380")
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()

        dialog.update_idletasks()
        x = parent_x - 440
        y = parent_y
        if y + 380 > 900:
            y = 520
        if y < 0:
            y = 0
        dialog.geometry(f"+{x}+{y}")
        dialog.attributes('-alpha', self.app.alpha)
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        ttk.Label(dialog, text="输入代码或名称搜索:", font=('Microsoft YaHei', 10)).pack(pady=(15, 5))

        input_frame = ttk.Frame(dialog)
        input_frame.pack(fill=tk.X, padx=20)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(input_frame, textvariable=self.search_var, width=32, font=('Arial', 11))
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.focus()

        ttk.Button(input_frame, text="搜索", command=self.search_stock, width=8).pack(side=tk.LEFT, padx=(5, 0))

        result_frame = ttk.Frame(dialog)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 5))

        self.result_listbox = tk.Listbox(result_frame, height=10, font=('Arial', 10))
        self.result_listbox.pack(fill=tk.BOTH, expand=True)
        self.result_listbox.bind('<Double-1>', lambda e: self.add_stock_from_list(dialog, keep_open=True))

        ttk.Label(dialog, text="双击列表项添加（可继续添加）", font=('Microsoft YaHei', 8), foreground='gray').pack(pady=(0, 5))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        ttk.Button(
            btn_frame,
            text="添加选中",
            command=lambda: self.add_stock_from_list(dialog, keep_open=True),
            width=10
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy, width=10).pack(side=tk.RIGHT)

        search_entry.bind('<Return>', lambda e: self.search_stock())
        self.search_results = []

    def search_stock(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            return

        self.result_listbox.delete(0, tk.END)
        self.search_results = []
        lower_keyword = keyword.lower()

        for symbol, name, asset, source in self._commodity_suggestions(lower_keyword):
            self.search_results.append((symbol, name, asset, source))
            self.result_listbox.insert(tk.END, f"{symbol} - {name} [{self._asset_label(asset)}]")

        try:
            url = "https://api.nasdaq.com/api/autocomplete/slookup/20"
            headers = self._nasdaq_headers()
            response = requests.get(
                url,
                params={'search': keyword},
                headers=headers,
                proxies=self.proxies,
                timeout=8
            )
            data = response.json()
            rows = data.get('data') if isinstance(data, dict) else None
            if isinstance(rows, list):
                seen = {item[0] for item in self.search_results}
                for row in rows:
                    asset = str(row.get('asset') or '').upper()
                    if asset not in ('STOCKS', 'ETF'):
                        continue
                    symbol = str(row.get('symbol') or '').upper().strip()
                    name = str(row.get('name') or symbol).strip()
                    if not symbol or symbol in seen:
                        continue
                    seen.add(symbol)
                    self.search_results.append((symbol, name, asset, 'nasdaq'))
                    self.result_listbox.insert(tk.END, f"{symbol} - {name} [{self._asset_label(asset)}]")
        except Exception as e:
            if not self.search_results:
                self.result_listbox.insert(tk.END, f"搜索失败: {str(e)}")

        if not self.search_results:
            self.result_listbox.insert(tk.END, "未找到匹配标的")

    def _commodity_suggestions(self, lower_keyword):
        candidates = [
            ("hf_GC", "纽约黄金 COMEX 连续", "FUTURES", "sina", ("gold", "黄金", "gc", "comex", "期货")),
            ("GLD", "SPDR Gold Shares", "ETF", "nasdaq", ("gold", "黄金", "gld")),
            ("IAU", "iShares Gold Trust", "ETF", "nasdaq", ("gold", "黄金", "iau")),
        ]
        if not lower_keyword:
            return []
        result = []
        for symbol, name, asset, source, keywords in candidates:
            haystack = ' '.join([symbol.lower(), name.lower(), *keywords])
            if (
                lower_keyword == symbol.lower()
                or lower_keyword in keywords
                or (len(lower_keyword) >= 3 and lower_keyword in haystack)
            ):
                result.append((symbol, name, asset, source))
        return result

    def add_stock_from_list(self, dialog, keep_open=False):
        selection = self.result_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个标的", parent=dialog)
            return

        idx = selection[0]
        if idx < len(self.search_results):
            symbol, name, asset, source = self.search_results[idx]
            if symbol in self.us_stocks:
                messagebox.showinfo("提示", f"{name} 已在列表中", parent=dialog)
            else:
                item = {'name': name, 'asset': asset, 'source': source}
                if symbol == 'hf_GC':
                    item['chart_symbol'] = 'GC'
                self.us_stocks[symbol] = item
                self.save_us_stocks()
                self.refresh_us_list()
                self.status_var.set(f"已添加: {name}")
                threading.Thread(target=self._manual_refresh_thread, daemon=True).start()
                if not keep_open:
                    dialog.destroy()

    def delete_selected_stock(self):
        selection = self.us_tree.selection()
        if not selection:
            return

        item = selection[0]
        symbol = str(self.us_tree.item(item)['values'][0])

        if symbol in self.us_stocks:
            name = self.us_stocks[symbol].get('name', symbol)
            del self.us_stocks[symbol]
            self.stock_data.pop(symbol, None)
            self.save_us_stocks()
            self.refresh_us_list()
            self.status_var.set(f"已删除: {name}")

    def show_context_menu(self, event):
        item = self.us_tree.identify_row(event.y)
        if item:
            self.us_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def on_stock_double_click(self, event):
        self.show_stock_chart()

    def on_source_change(self, event=None):
        self.status_var.set(f"数据源: {self.selected_source.get()}")

    def _nasdaq_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.nasdaq.com/market-activity/stocks',
            'Origin': 'https://www.nasdaq.com',
        }

    def _cnbc_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.cnbc.com/quotes/',
        }

    def _sina_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
            'Referer': 'https://finance.sina.com.cn',
        }

    def _new_york_now(self):
        now_utc = dt.datetime.now(dt.timezone.utc)
        try:
            return now_utc.astimezone(ZoneInfo('America/New_York'))
        except Exception:
            offset_hours = -4 if 3 <= now_utc.month <= 11 else -5
            return now_utc.astimezone(dt.timezone(dt.timedelta(hours=offset_hours)))

    def _is_us_overnight_now(self):
        now = self._new_york_now()
        minutes = now.hour * 60 + now.minute
        weekday = now.weekday()
        if minutes >= 20 * 60:
            return weekday in (6, 0, 1, 2, 3)
        if minutes < 4 * 60:
            return weekday in (0, 1, 2, 3, 4)
        return False

    def _get_alpaca_credentials(self):
        key = (
            os.environ.get('ALPACA_API_KEY')
            or os.environ.get('ALPACA_KEY_ID')
            or os.environ.get('APCA_API_KEY_ID')
        )
        secret = (
            os.environ.get('ALPACA_API_SECRET')
            or os.environ.get('ALPACA_SECRET_KEY')
            or os.environ.get('APCA_API_SECRET_KEY')
        )
        return key, secret

    def _alpaca_headers(self):
        key, secret = self._get_alpaca_credentials()
        if not key or not secret:
            if not self._alpaca_missing_credentials_logged:
                print("Alpaca夜盘未配置 API Key，已跳过夜盘源")
                self._alpaca_missing_credentials_logged = True
            return None
        self._alpaca_missing_credentials_logged = False
        return {
            'accept': 'application/json',
            'APCA-API-KEY-ID': key,
            'APCA-API-SECRET-KEY': secret,
        }

    def _quote_midpoint(self, quote_data):
        bid = self._to_float(quote_data.get('bp'))
        ask = self._to_float(quote_data.get('ap'))
        if bid and ask:
            return (bid + ask) / 2
        return ask or bid

    def _asset_label(self, asset):
        labels = {
            'STOCKS': '美股',
            'ETF': 'ETF',
            'FUTURES': '期货',
        }
        return labels.get(str(asset).upper(), str(asset))

    def _session_label(self, session):
        text = str(session or '').strip()
        upper = text.upper().replace('-', '_').replace(' ', '_')
        mapping = {
            'PRE_MARKET': '盘前',
            'PRE_MKT': '盘前',
            'PREMARKET': '盘前',
            'MARKET_OPEN': '盘中',
            'REGULAR_MARKET': '盘中',
            'REG_MKT': '盘中',
            'OPEN': '盘中',
            'AFTER_HOURS': '盘后',
            'POST_MARKET': '盘后',
            'POST_MKT': '盘后',
            'CLOSED': '休市',
            'CLOSE': '休市',
            'HALTED': '停牌',
        }
        if upper in mapping:
            return mapping[upper]
        if 'PRE' in upper:
            return '盘前'
        if 'AFTER' in upper or 'POST' in upper:
            return '盘后'
        if 'OPEN' in upper or 'REG' in upper:
            return '盘中'
        if 'CLOSE' in upper:
            return '休市'
        return text or '--'

    def _to_float(self, value, default=None):
        if value is None:
            return default
        if isinstance(value, (int, float)):
            number = float(value)
            return number if np.isfinite(number) else default
        text = str(value).strip()
        if not text or text.upper() in ('N/A', 'NA', '--', 'UNCH'):
            return default
        text = text.replace('$', '').replace('%', '').replace(',', '').replace('+', '')
        try:
            number = float(text)
            return number if np.isfinite(number) else default
        except ValueError:
            return default

    def _clean_text(self, value):
        try:
            return str(value).encode('gbk', errors='ignore').decode('gbk', errors='ignore')
        except Exception:
            return str(value)

    def _display_name(self, value, max_len=14):
        text = self._clean_text(value)
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + '...'

    def _format_price(self, value):
        value = self._to_float(value, None)
        if value is None:
            return '--'
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        if abs(value) >= 1:
            return f"{value:.2f}"
        return f"{value:.4f}"

    def _format_volume(self, value):
        value = self._to_float(value, None)
        if value is None:
            return '--'
        if value >= 100000000:
            return f'{value / 100000000:.2f}亿'
        if value >= 10000:
            return f'{value / 10000:.2f}万'
        return f'{value:.0f}'

    def _format_amount(self, value):
        return self._format_volume(value)

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

    def _get_chart_figure(self, frame, figsize):
        canvas = getattr(frame, '_chart_canvas', None)
        if canvas and canvas.get_tk_widget().winfo_exists():
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
        canvas.draw_idle()

    def _show_chart_message(self, frame, text, font=('Microsoft YaHei', 12)):
        if frame.winfo_children():
            for child in frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(text=text)
                    return
            return
        ttk.Label(frame, text=text, font=font).pack(pady=50)

    def _extract_jsonp(self, content):
        match = re.search(r'var\s+\w+\s*=\s*\((.*)\)\s*;?\s*$', content, re.DOTALL)
        if not match:
            match = re.search(r'var\s+\w+\s*=\s*(\[.*\]|\{.*\})\s*;?\s*$', content, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(1))

    def fetch_nasdaq_quote(self, symbol, asset):
        assetclass = 'etf' if str(asset).upper() == 'ETF' else 'stocks'
        url = f"https://api.nasdaq.com/api/quote/{quote(symbol)}/info"
        response = requests.get(
            url,
            params={'assetclass': assetclass},
            headers=self._nasdaq_headers(),
            proxies=self.proxies,
            timeout=self.request_timeout
        )
        data = response.json()
        quote_data = data.get('data') if isinstance(data, dict) else None
        if not quote_data:
            return None

        primary = quote_data.get('primaryData') or {}
        secondary = quote_data.get('secondaryData') or {}
        price = self._to_float(primary.get('lastSalePrice'))
        if price is None:
            return None

        change_amount = self._to_float(primary.get('netChange'), 0)
        change = self._to_float(primary.get('percentageChange'), 0)
        previous_close = self._to_float(secondary.get('lastSalePrice'))
        if previous_close is None and change_amount is not None:
            previous_close = price - change_amount

        day_range = str((quote_data.get('keyStats') or {}).get('dayrange', {}).get('value') or '')
        low_price = high_price = None
        if '-' in day_range and 'NA' not in day_range.upper():
            parts = day_range.split('-', 1)
            low_price = self._to_float(parts[0])
            high_price = self._to_float(parts[1])

        return {
            'symbol': symbol,
            'name': quote_data.get('companyName') or symbol,
            'asset': 'ETF' if str(quote_data.get('assetClass') or asset).upper() == 'ETF' else 'STOCKS',
            'source': 'Nasdaq',
            'price': price,
            'change_amount': change_amount or 0,
            'change': change or 0,
            'previous_close': previous_close,
            'open': None,
            'high': high_price,
            'low': low_price,
            'volume': self._to_float(primary.get('volume')),
            'session': self._session_label(quote_data.get('marketStatus')),
            'raw_session': quote_data.get('marketStatus'),
            'time': primary.get('lastTradeTimestamp'),
        }

    def fetch_cnbc_quote(self, symbol, item=None):
        url = "https://quote.cnbc.com/quote-html-webservice/quote.htm"
        response = requests.get(
            url,
            params={'symbols': symbol, 'requestMethod': 'extended', 'output': 'json'},
            headers=self._cnbc_headers(),
            proxies=self.proxies,
            timeout=self.request_timeout
        )
        data = response.json()
        quote_rows = (
            data.get('ExtendedQuoteResult', {})
            .get('ExtendedQuote', {})
            .get('QuickQuote', [])
        )
        if isinstance(quote_rows, dict):
            quote_rows = [quote_rows]
        if not quote_rows:
            return None
        row = quote_rows[0]
        if str(row.get('code', '0')) != '0':
            return None

        price = self._to_float(row.get('last'))
        if price is None:
            return None
        previous_close = self._to_float(row.get('previous_day_closing'))
        change_amount = self._to_float(row.get('change'), 0)
        change = self._to_float(row.get('change_pct'), 0)
        asset_type = str(row.get('assetType') or row.get('type') or '').upper()
        asset_subtype = str(row.get('assetSubType') or row.get('subType') or '').upper()
        asset = 'FUTURES' if 'DERIVATIVE' in asset_type or 'FUTURE' in asset_subtype else (item or {}).get('asset', 'STOCKS')

        return {
            'symbol': symbol,
            'name': row.get('name') or (item or {}).get('name') or symbol,
            'asset': asset,
            'source': 'CNBC',
            'price': price,
            'change_amount': change_amount or 0,
            'change': change or 0,
            'previous_close': previous_close,
            'open': self._to_float(row.get('open')),
            'high': self._to_float(row.get('high')),
            'low': self._to_float(row.get('low')),
            'volume': self._to_float(row.get('fullVolume') or row.get('volume')),
            'session': self._session_label(row.get('curmktstatus')),
            'raw_session': row.get('curmktstatus'),
            'time': row.get('last_time') or row.get('responseTime'),
        }

    def fetch_alpaca_overnight_quote(self, symbol, item=None):
        if not self._is_us_overnight_now():
            return None

        headers = self._alpaca_headers()
        if headers is None:
            return None

        try:
            response = requests.get(
                f"https://data.alpaca.markets/v2/stocks/{quote(symbol)}/snapshot",
                params={'feed': 'overnight'},
                headers=headers,
                proxies=self.proxies,
                timeout=self.request_timeout
            )
            if response.status_code in (401, 403):
                print(f"Alpaca夜盘获取{symbol}失败: API Key 无权限或无效")
                return None
            response.raise_for_status()
            data = response.json()
            snapshot = data.get('snapshot') if isinstance(data, dict) else None
            if not isinstance(snapshot, dict):
                snapshot = data if isinstance(data, dict) else None
            if not snapshot:
                return None

            latest_quote = snapshot.get('latestQuote') or {}
            latest_trade = snapshot.get('latestTrade') or {}
            minute_bar = snapshot.get('minuteBar') or {}
            daily_bar = snapshot.get('dailyBar') or {}
            prev_bar = snapshot.get('prevDailyBar') or {}

            price = self._quote_midpoint(latest_quote)
            if price is None:
                price = self._to_float(latest_trade.get('p'))
            if price is None:
                price = self._to_float(minute_bar.get('c'))
            if price is None:
                return None

            previous_close = self._to_float(prev_bar.get('c'))
            change_amount = price - previous_close if previous_close else 0
            change = (change_amount / previous_close * 100) if previous_close else 0
            quote_time = latest_quote.get('t') or latest_trade.get('t') or minute_bar.get('t')

            return {
                'symbol': symbol,
                'name': (item or {}).get('name') or symbol,
                'asset': (item or {}).get('asset', 'STOCKS'),
                'source': 'Alpaca夜盘',
                'price': price,
                'change_amount': change_amount,
                'change': change,
                'previous_close': previous_close,
                'open': self._to_float(daily_bar.get('o')),
                'high': self._to_float(daily_bar.get('h')),
                'low': self._to_float(daily_bar.get('l')),
                'volume': self._to_float(daily_bar.get('v') or minute_bar.get('v')),
                'session': '夜盘',
                'raw_session': 'OVERNIGHT',
                'time': quote_time or time.strftime('%H:%M:%S'),
            }
        except Exception as e:
            print(f"Alpaca夜盘获取{symbol}失败: {e}")
            return None

    def fetch_sina_futures_quote(self, symbol, item=None):
        response = requests.get(
            "https://hq.sinajs.cn/list=" + symbol,
            headers=self._sina_headers(),
            proxies=self.proxies,
            timeout=self.request_timeout
        )
        content = response.content.decode('gb18030', errors='ignore')
        match = re.search(r'hq_str_(\w+)="([^"]*)"', content)
        if not match:
            return None
        parts = match.group(2).split(',')
        if len(parts) < 14:
            return None

        price = self._to_float(parts[0])
        previous_close = self._to_float(parts[7])
        if price is None:
            return None
        change_amount = price - previous_close if previous_close else 0
        change = (change_amount / previous_close * 100) if previous_close else 0

        return {
            'symbol': symbol,
            'name': parts[13] or (item or {}).get('name') or symbol,
            'asset': 'FUTURES',
            'source': '新浪外盘',
            'price': price,
            'change_amount': change_amount,
            'change': change,
            'previous_close': previous_close,
            'open': self._to_float(parts[8]),
            'high': self._to_float(parts[4]),
            'low': self._to_float(parts[5]),
            'volume': self._to_float(parts[9]),
            'session': '夜盘',
            'raw_session': 'GLOBAL_FUTURES',
            'time': f"{parts[12]} {parts[6]}",
        }

    def fetch_price(self, symbol, item):
        asset = str(item.get('asset', 'STOCKS')).upper()
        source = str(item.get('source', '')).lower()
        selected = self.selected_source.get()

        if asset == 'FUTURES':
            if source == 'sina' or symbol.startswith('hf_'):
                try:
                    data = self.fetch_sina_futures_quote(symbol, item)
                except Exception as e:
                    print(f"新浪外盘获取{symbol}失败: {e}")
                    data = None
                if data:
                    return data
            try:
                return self.fetch_cnbc_quote(symbol, item)
            except Exception as e:
                print(f"CNBC获取{symbol}失败: {e}")
                return None

        overnight = self._is_us_overnight_now()
        if selected == "Alpaca夜盘" or overnight:
            try:
                data = self.fetch_alpaca_overnight_quote(symbol, item)
            except Exception as e:
                print(f"Alpaca夜盘获取{symbol}失败: {e}")
                data = None
            if data:
                return data

        if selected == "CNBC备用":
            try:
                return self.fetch_cnbc_quote(symbol, item)
            except Exception as e:
                print(f"CNBC获取{symbol}失败: {e}")
                return None

        try:
            data = self.fetch_nasdaq_quote(symbol, asset)
        except Exception as e:
            print(f"Nasdaq获取{symbol}失败: {e}")
            data = None
        if data and overnight and data.get('raw_session') == 'Closed':
            data['session'] = '夜盘无源'
            data['source'] = 'Nasdaq收盘'
        if data:
            return data
        try:
            return self.fetch_cnbc_quote(symbol, item)
        except Exception as e:
            print(f"CNBC获取{symbol}失败: {e}")
            return None

    def refresh_us_list(self):
        for item in self.us_tree.get_children():
            self.us_tree.delete(item)

        for symbol, item in self.us_stocks.items():
            name = self._display_name(item.get('name', symbol))
            if symbol in self.stock_data:
                data = self.stock_data[symbol]
                price_str = self._format_price(data.get('price'))
                change_amount = data.get('change_amount') or 0
                change = data.get('change') or 0
                change_amount_str = f"{change_amount:+.2f}"
                change_str = f"{change:+.2f}%"
                session = data.get('session') or '--'
                if data.get('name') and data.get('name') != symbol:
                    name = self._display_name(data.get('name'))

                if change > 0:
                    tag = 'up'
                elif change < 0:
                    tag = 'down'
                else:
                    tag = 'flat'

                self.us_tree.insert(
                    '',
                    'end',
                    values=(symbol, name, price_str, change_amount_str, change_str, session),
                    tags=(tag,)
                )
            else:
                self.us_tree.insert('', 'end', values=(symbol, name, "--", "--", "--", "--"), tags=('flat',))

    def _refresh_prices_once(self):
        symbols = list(self.us_stocks.keys())
        if not symbols:
            self.after(0, self.refresh_us_list)
            return

        max_workers = min(8, len(symbols))
        success_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch_price, symbol, self.us_stocks[symbol]): symbol
                for symbol in symbols
                if self.running
            }
            for future in as_completed(futures):
                if not self.running:
                    break
                symbol = futures[future]
                try:
                    data = future.result()
                except Exception as e:
                    print(f"刷新{symbol}失败: {e}")
                    continue
                if data is not None:
                    self.stock_data[symbol] = data
                    if data.get('name') and symbol in self.us_stocks:
                        self.us_stocks[symbol]['name'] = data['name']
                    success_count += 1

        self.after(0, self.refresh_us_list)
        current_time = time.strftime("%H:%M:%S")
        self.after(0, lambda: self.update_time_var.set(f"最后更新: {current_time}"))
        if success_count:
            self.after(0, lambda: self.status_var.set(f"更新成功: {success_count}/{len(symbols)}"))
        else:
            self.after(0, lambda: self.status_var.set("所有数据源失败"))

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
                self._refresh_prices_once()
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
            self._refresh_prices_once()
            self.after(0, lambda: self.status_var.set("手动刷新完成"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"刷新失败: {str(e)}"))
        finally:
            self.update_lock.release()

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

        now = time.monotonic()
        refresh_kline = (
            now - context.get('last_kline_refresh', 0)
        ) * 1000 >= self.chart_kline_refresh_interval_ms
        context['refresh_in_progress'] = True

        def fetch_in_background():
            try:
                realtime_data = self.fetch_intraday_data(context['symbol'], context['item'])
                kline_data = self.fetch_kline_data(context['symbol'], context['item']) if refresh_kline else None
            except Exception as e:
                print(f"刷新美股走势图失败: {e}")
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
                len(realtime_data), tuple(realtime_data[-1][:2])
            ) if realtime_data else None
            if realtime_signature and realtime_signature != context.get('last_realtime_signature'):
                self.draw_realtime_chart(
                    context['realtime_frame'],
                    context['symbol'],
                    context['name'],
                    context['item'],
                    realtime_data=realtime_data
                )
                context['last_realtime_signature'] = realtime_signature
            elif not realtime_signature:
                self._show_chart_message(context['realtime_frame'], "获取分时数据失败")

            if refresh_kline:
                kline_signature = (
                    len(kline_data), tuple(kline_data[-1][:5])
                ) if kline_data else None
                if kline_signature and kline_signature != context.get('last_kline_signature'):
                    self.draw_stock_chart(
                        context['kline_frame'],
                        context['symbol'],
                        context['name'],
                        context['item'],
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
        selection = self.us_tree.selection()
        if not selection:
            return

        tree_item = selection[0]
        values = self.us_tree.item(tree_item)['values']
        symbol = str(values[0])
        item = self.us_stocks.get(symbol)
        if not item:
            return
        name = item.get('name') or symbol

        if self.chart_window is not None and self.chart_window.winfo_exists():
            self._close_chart_window()

        chart_window = tk.Toplevel(self.winfo_toplevel())
        chart_window.title(f"{name} ({symbol}) - 行情走势")
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
            'symbol': symbol,
            'name': name,
            'item': item,
            'refresh_in_progress': True,
            'last_kline_refresh': time.monotonic(),
        }
        self._show_chart_message(realtime_frame, "分时数据加载中...")
        self._show_chart_message(kline_frame, "K线数据加载中...")
        context = self.chart_context

        def fetch_initial_chart():
            try:
                realtime_data = self.fetch_intraday_data(symbol, item)
                kline_data = self.fetch_kline_data(symbol, item)
            except Exception as e:
                print(f"初始加载美股走势图失败: {e}")
                realtime_data = None
                kline_data = None
            self.chart_refresh_queue.put((context, realtime_data, kline_data, True))

        threading.Thread(target=fetch_initial_chart, daemon=True).start()
        context['refresh_poll_job'] = chart_window.after(100, self._poll_chart_refresh_queue)

    def fetch_intraday_data(self, symbol, item):
        if item.get('asset') == 'FUTURES' and (item.get('source') == 'sina' or symbol.startswith('hf_')):
            return self.fetch_sina_futures_intraday(symbol, item)
        return self.fetch_nasdaq_intraday(symbol, item)

    def fetch_nasdaq_intraday(self, symbol, item):
        assetclass = 'etf' if item.get('asset') == 'ETF' else 'stocks'
        response = requests.get(
            f"https://api.nasdaq.com/api/quote/{quote(symbol)}/chart",
            params={'assetclass': assetclass},
            headers=self._nasdaq_headers(),
            proxies=self.proxies,
            timeout=10
        )
        data = response.json()
        chart_data = (data.get('data') or {}).get('chart') if isinstance(data, dict) else None
        if not chart_data:
            return None
        result = []
        for row in chart_data:
            price = self._to_float(row.get('y'))
            if price is None:
                continue
            label = (row.get('z') or {}).get('dateTime') or ''
            result.append([label, price, 0, np.nan])
        return result

    def fetch_sina_futures_intraday(self, symbol, item):
        chart_symbol = item.get('chart_symbol') or symbol.replace('hf_', '')
        response = requests.get(
            "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_data=/GlobalFuturesService.getGlobalFuturesMinLine",
            params={'symbol': chart_symbol},
            headers=self._sina_headers(),
            proxies=self.proxies,
            timeout=10
        )
        content = response.content.decode('gbk', errors='ignore')
        data = self._extract_jsonp(content)
        rows = data.get('minLine_1d') if isinstance(data, dict) else None
        if not rows:
            return None
        result = []
        for row in rows:
            if len(row) >= 10:
                time_label = row[4]
                price = self._to_float(row[5])
                volume = self._to_float(row[6], 0)
                avg_price = self._to_float(row[8], np.nan)
            elif len(row) >= 6:
                time_label = row[0]
                price = self._to_float(row[1])
                volume = self._to_float(row[2], 0)
                avg_price = self._to_float(row[4], np.nan)
            else:
                continue
            if price is not None:
                result.append([time_label, price, volume, avg_price])
        return result

    def fetch_kline_data(self, symbol, item):
        if item.get('asset') == 'FUTURES' and (item.get('source') == 'sina' or symbol.startswith('hf_')):
            return self.fetch_sina_futures_kline(symbol, item)
        return self.fetch_nasdaq_kline(symbol, item)

    def fetch_nasdaq_kline(self, symbol, item):
        assetclass = 'etf' if item.get('asset') == 'ETF' else 'stocks'
        today = dt.date.today()
        from_date = today - dt.timedelta(days=140)
        response = requests.get(
            f"https://api.nasdaq.com/api/quote/{quote(symbol)}/historical",
            params={
                'assetclass': assetclass,
                'fromdate': from_date.strftime('%Y-%m-%d'),
                'todate': today.strftime('%Y-%m-%d'),
                'limit': 100,
            },
            headers=self._nasdaq_headers(),
            proxies=self.proxies,
            timeout=10
        )
        data = response.json()
        rows = (
            (data.get('data') or {})
            .get('tradesTable', {})
            .get('rows', [])
        ) if isinstance(data, dict) else []
        result = []
        for row in rows:
            try:
                date_text = dt.datetime.strptime(row['date'], '%m/%d/%Y').strftime('%Y-%m-%d')
            except Exception:
                date_text = row.get('date', '')
            open_price = self._to_float(row.get('open'))
            close_price = self._to_float(row.get('close'))
            high_price = self._to_float(row.get('high'))
            low_price = self._to_float(row.get('low'))
            volume = self._to_float(row.get('volume'), 0)
            if None in (open_price, close_price, high_price, low_price):
                continue
            amount = close_price * volume if volume else 0
            result.append([date_text, open_price, close_price, high_price, low_price, volume, amount])
        result.reverse()
        return result[-80:] if result else None

    def fetch_sina_futures_kline(self, symbol, item):
        chart_symbol = item.get('chart_symbol') or symbol.replace('hf_', '')
        response = requests.get(
            "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_data=/GlobalFuturesService.getGlobalFuturesDailyKLine",
            params={'symbol': chart_symbol},
            headers=self._sina_headers(),
            proxies=self.proxies,
            timeout=10
        )
        content = response.content.decode('gbk', errors='ignore')
        data = self._extract_jsonp(content)
        if not isinstance(data, list):
            return None
        result = []
        for row in data[-80:]:
            open_price = self._to_float(row.get('open'))
            close_price = self._to_float(row.get('close'))
            high_price = self._to_float(row.get('high'))
            low_price = self._to_float(row.get('low'))
            volume = self._to_float(row.get('volume'), 0)
            if None in (open_price, close_price, high_price, low_price):
                continue
            result.append([
                row.get('date', ''),
                open_price,
                close_price,
                high_price,
                low_price,
                volume,
                close_price * volume if volume else 0,
            ])
        return result if result else None

    def draw_realtime_chart(self, frame, symbol, name, item, realtime_data=None):
        try:
            if realtime_data is None:
                realtime_data = self.fetch_intraday_data(symbol, item)
            if not realtime_data:
                self._show_chart_message(frame, "获取分时数据失败")
                return

            times = []
            prices = []
            avg_prices = []
            volumes = []
            for row in realtime_data:
                if len(row) < 2:
                    continue
                price = self._to_float(row[1])
                if price is None:
                    continue
                times.append(str(row[0]))
                prices.append(price)
                volumes.append(self._to_float(row[2], 0) if len(row) > 2 else 0)
                avg_prices.append(self._to_float(row[3], np.nan) if len(row) > 3 else np.nan)

            if not prices:
                self._show_chart_message(frame, "分时数据为空")
                return

            palette = self._chart_palette()
            x = np.arange(len(prices))
            price_array = np.asarray(prices, dtype=float)
            snapshot = self.stock_data.get(symbol, {})
            previous_close = self._to_float(snapshot.get('previous_close'), prices[0])
            if not previous_close:
                previous_close = prices[0]
            change_abs = prices[-1] - previous_close
            change_pct = (change_abs / previous_close * 100) if previous_close else 0
            change_color = palette['up'] if change_abs >= 0 else palette['down']

            avg_array = np.asarray(avg_prices, dtype=float)
            if len(avg_array) != len(price_array) or np.isfinite(avg_array).sum() < max(2, len(price_array) // 4):
                avg_array = np.cumsum(price_array) / np.arange(1, len(price_array) + 1)

            fig, canvas = self._get_chart_figure(frame, (9.0, 5.7))
            fig.patch.set_facecolor(palette['bg'])
            gs = fig.add_gridspec(2, 1, height_ratios=[3.3, 1.35], hspace=0.07)
            ax_price = fig.add_subplot(gs[0])
            ax_macd = fig.add_subplot(gs[1], sharex=ax_price)
            fig.subplots_adjust(left=0.055, right=0.94, top=0.815, bottom=0.09, hspace=0.06)

            clean_name = self._clean_text(name)
            updated_at = time.strftime('%H:%M:%S')
            session = snapshot.get('session') or self._session_label(snapshot.get('raw_session'))
            fig.text(0.045, 0.965, f'{clean_name} ({symbol})  分时走势',
                     color=palette['text'], fontsize=12, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.72, 0.965, f'{session}   更新 {updated_at}   自动刷新 5秒',
                     color=palette['muted'], fontsize=8, ha='left',
                     fontname='Microsoft YaHei')
            fig.text(0.045, 0.880, self._format_price(prices[-1]),
                     color=change_color, fontsize=21, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.900, f'{change_abs:+.2f}',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.862, f'{change_pct:+.2f}%',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.345, 0.905,
                     f'昨收 {self._format_price(previous_close)}     今开 {self._format_price(snapshot.get("open"))}     最高 {self._format_price(snapshot.get("high"))}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')
            fig.text(0.345, 0.865,
                     f'最低 {self._format_price(snapshot.get("low"))}     均价 {self._format_price(avg_array[-1])}     量 {self._format_volume(snapshot.get("volume"))}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')

            self._style_chart_axis(ax_price, palette, hide_x=True)
            ax_price.axhline(y=previous_close, color=palette['zero'], linestyle='--', linewidth=0.8, alpha=0.85)
            ax_price.fill_between(x, price_array, previous_close,
                                  where=price_array >= previous_close,
                                  color=palette['up'], alpha=0.055, interpolate=True)
            ax_price.fill_between(x, price_array, previous_close,
                                  where=price_array < previous_close,
                                  color=palette['down'], alpha=0.055, interpolate=True)
            ax_price.plot(x, price_array, color=palette['price'], linewidth=1.35, label='分时', zorder=4)
            ax_price.plot(x, avg_array, color=palette['avg'], linewidth=1.5, linestyle=(0, (5, 2)), label='均价', zorder=5)
            ax_price.scatter([x[-1]], [prices[-1]], s=20, color=change_color, zorder=6)
            ax_price.annotate(self._format_price(prices[-1]), xy=(x[-1], prices[-1]),
                              xytext=(8, 0), textcoords='offset points', va='center',
                              color=change_color, fontsize=8,
                              bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=change_color, lw=0.8),
                              clip_on=False)
            ax_price.legend(loc='upper left', fontsize=8, frameon=False, ncol=2)
            ax_price.set_xlim(0, max(1, len(prices) - 1))
            price_delta = max(abs(max(prices) - previous_close), abs(min(prices) - previous_close), previous_close * 0.002, 0.01)
            ax_price.set_ylim(previous_close - price_delta * 1.14, previous_close + price_delta * 1.14)

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

            tick_count = min(8, len(times))
            tick_positions = sorted(set(np.linspace(0, len(times) - 1, tick_count, dtype=int).tolist()))
            ax_macd.set_xticks(tick_positions)
            ax_macd.set_xticklabels([times[i].replace(' ET', '') for i in tick_positions],
                                    fontsize=8, color=palette['axis'])

            self._draw_chart_figure(frame, fig, canvas)

        except Exception as e:
            self._show_chart_message(frame, f"绘制分时图失败: {str(e)}")

    def draw_stock_chart(self, frame, symbol, name, item, kline_data=None):
        try:
            if kline_data is None:
                kline_data = self.fetch_kline_data(symbol, item)
            if not kline_data:
                self._show_chart_message(frame, "获取K线数据失败")
                return

            dates = []
            opens = []
            closes = []
            highs = []
            lows = []
            volumes = []
            amounts = []
            for row in kline_data:
                if len(row) < 6:
                    continue
                dates.append(str(row[0]))
                opens.append(float(row[1]))
                closes.append(float(row[2]))
                highs.append(float(row[3]))
                lows.append(float(row[4]))
                volumes.append(float(row[5] or 0))
                amounts.append(float(row[6] or 0) if len(row) > 6 else float(row[2]) * float(row[5] or 0))

            if not dates:
                self._show_chart_message(frame, "K线数据为空")
                return

            palette = self._chart_palette()
            x = np.arange(len(dates))
            bar_width = 0.62
            candle_colors = [palette['up'] if close_price >= open_price else palette['down']
                             for open_price, close_price in zip(opens, closes)]
            volume_colors = []
            for i, close_price in enumerate(closes):
                reference = closes[i - 1] if i > 0 else opens[i]
                volume_colors.append(palette['up'] if close_price >= reference else palette['down'])

            previous_close = closes[-2] if len(closes) > 1 else opens[-1]
            change_abs = closes[-1] - previous_close
            change_pct = (change_abs / previous_close * 100) if previous_close else 0
            change_color = palette['up'] if change_abs >= 0 else palette['down']

            fig, canvas = self._get_chart_figure(frame, (9.0, 5.7))
            fig.patch.set_facecolor(palette['bg'])
            gs = fig.add_gridspec(3, 1, height_ratios=[3.2, 1.0, 1.35], hspace=0.06)
            ax_price = fig.add_subplot(gs[0])
            ax_volume = fig.add_subplot(gs[1], sharex=ax_price)
            ax_macd = fig.add_subplot(gs[2], sharex=ax_price)
            fig.subplots_adjust(left=0.055, right=0.94, top=0.815, bottom=0.09, hspace=0.06)

            clean_name = self._clean_text(name)
            updated_at = time.strftime('%H:%M:%S')
            fig.text(0.045, 0.965, f'{clean_name} ({symbol})  日K走势',
                     color=palette['text'], fontsize=12, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.77, 0.965, f'更新 {updated_at}   日K每30秒刷新',
                     color=palette['muted'], fontsize=8, ha='left',
                     fontname='Microsoft YaHei')
            fig.text(0.045, 0.880, self._format_price(closes[-1]),
                     color=change_color, fontsize=21, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.900, f'{change_abs:+.2f}',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.215, 0.862, f'{change_pct:+.2f}%',
                     color=change_color, fontsize=11, fontweight='bold',
                     fontname='Microsoft YaHei')
            fig.text(0.345, 0.905,
                     f'开 {self._format_price(opens[-1])}     高 {self._format_price(highs[-1])}     低 {self._format_price(lows[-1])}',
                     color=palette['axis'], fontsize=9, fontname='Microsoft YaHei')
            fig.text(0.345, 0.865,
                     f'量 {self._format_volume(volumes[-1])}     日期 {dates[-1]}',
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

            for period, color, label in [
                (5, palette['ma5'], 'MA5'),
                (10, palette['ma10'], 'MA10'),
                (20, palette['ma20'], 'MA20'),
            ]:
                ma_values = self._moving_average(closes, period)
                if len(ma_values):
                    ax_price.plot(x, ma_values, color=color, linewidth=1.0, label=label)

            if price_span <= 0:
                price_span = max(closes[-1] * 0.02, 0.02)
            ax_price.set_ylim(min(lows) - price_span * 0.08, max(highs) + price_span * 0.08)
            ax_price.set_xlim(-1, len(dates))
            ax_price.legend(loc='upper left', fontsize=8, frameon=False, ncol=4)

            self._style_chart_axis(ax_volume, palette, hide_x=True)
            ax_volume.bar(x, volumes, color=volume_colors, width=bar_width, alpha=0.72)
            volume_max = max(volumes) if volumes else 0
            ax_volume.set_ylim(0, volume_max * 1.25 if volume_max > 0 else 1)
            ax_volume.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: self._format_volume(value)))
            ax_volume.yaxis.offsetText.set_visible(False)
            ax_volume.text(0.01, 0.78, f'成交量 {self._format_volume(volumes[-1])}',
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

            tick_count = min(9, len(dates))
            tick_positions = sorted(set(np.linspace(0, len(dates) - 1, tick_count, dtype=int).tolist()))
            short_dates = [dates[i][5:] if len(dates[i]) > 5 else dates[i] for i in tick_positions]
            ax_macd.set_xticks(tick_positions)
            ax_macd.set_xticklabels(short_dates, rotation=0, fontsize=8, color=palette['axis'])

            self._draw_chart_figure(frame, fig, canvas)

        except Exception as e:
            self._show_chart_message(frame, f"绘制走势图失败: {str(e)}")
