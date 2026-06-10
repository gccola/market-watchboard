#!/usr/bin/env python3
"""期货选项卡：XAUUSD、XAGUSD、CLMAIN 的 24H 实时行情。"""

import datetime as dt
import json
import os
import re
import threading
import time

import matplotlib

matplotlib.use('TkAgg')
matplotlib.rcParams['font.sans-serif'] = [
    'Microsoft YaHei', 'SimHei', 'Microsoft JhengHei', 'SimSun', 'DejaVu Sans'
]
matplotlib.rcParams['axes.unicode_minus'] = False
import requests
import tkinter as tk
from matplotlib import dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from tkinter import ttk


def get_app_dir():
    return os.path.dirname(os.path.abspath(__file__))


class FuturesFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        self.proxies = self.get_system_proxies()
        self.running = True
        self.active = False
        self.window_visible = True
        self.refresh_interval = 10.0
        self.background_refresh_interval = 300.0
        self.hidden_refresh_interval = 900.0
        self.request_timeout = 8.0
        self.update_lock = threading.Lock()
        self._refresh_now = threading.Event()

        self.futures = {
            "XAUUSD": {"name": "黄金", "quote_symbol": "hf_GC", "chart_symbol": "GC"},
            "XAGUSD": {"name": "白银", "quote_symbol": "hf_SI", "chart_symbol": "SI"},
            "CLMAIN": {"name": "WTI原油", "quote_symbol": "hf_CL", "chart_symbol": "CL"},
        }
        self.stock_data = {}

        self.chart_window = None
        self.chart_context = None
        self.chart_canvas = None
        self.chart_figure = None
        self.chart_refresh_job = None
        self.chart_refresh_interval_ms = 60000

        self.create_widgets()
        self.update_thread = threading.Thread(target=self.update_prices, daemon=True)
        self.update_thread.start()

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
        return proxies if proxies else None

    def _sina_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
            'Referer': 'https://finance.sina.com.cn',
        }

    def _to_float(self, value, default=None):
        if value is None:
            return default
        if isinstance(value, (int, float)):
            number = float(value)
            return number if number == number and number not in (float('inf'), float('-inf')) else default
        text = str(value).strip()
        if not text or text.upper() in ('N/A', 'NA', '--', 'NULL', 'UNCH'):
            return default
        text = text.replace('$', '').replace('%', '').replace(',', '').replace('+', '')
        try:
            number = float(text)
            return number if number == number and number not in (float('inf'), float('-inf')) else default
        except ValueError:
            return default

    def _format_price(self, value):
        value = self._to_float(value, None)
        if value is None:
            return '--'
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        if abs(value) >= 1:
            return f"{value:.2f}"
        return f"{value:.4f}"

    def _clean_text(self, value):
        try:
            return str(value).encode('gbk', errors='ignore').decode('gbk', errors='ignore')
        except Exception:
            return str(value)

    def _extract_jsonp(self, content):
        match = re.search(r'var\s+\w+\s*=\s*\((.*)\)\s*;?\s*$', content, re.DOTALL)
        if not match:
            match = re.search(r'var\s+\w+\s*=\s*(\[.*\]|\{.*\})\s*;?\s*$', content, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(1))

    def _symbol_item(self, symbol):
        return self.futures.get(symbol, {'name': symbol, 'quote_symbol': symbol, 'chart_symbol': symbol})

    def _current_refresh_interval(self):
        if not self.window_visible:
            return self.hidden_refresh_interval
        if not self.active:
            return self.background_refresh_interval
        return self.refresh_interval

    def _wait_for_next_refresh(self, seconds):
        self._refresh_now.wait(max(0.05, seconds))
        self._refresh_now.clear()

    def set_refresh_active(self, active, visible=True):
        was_active = self.active
        self.active = bool(active)
        self.window_visible = bool(visible)
        if self.active and not was_active:
            self.request_refresh()

    def request_refresh(self):
        self._refresh_now.set()

    def create_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        title_frame = ttk.Frame(self)
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        title_frame.columnconfigure(1, weight=1)

        ttk.Label(title_frame, text="期货", font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(title_frame, text="刷新", command=self.manual_refresh).grid(row=0, column=2, sticky=tk.E)

        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ('symbol', 'name', 'price', 'change_amount', 'change', 'high', 'low')
        self.futures_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        self.futures_tree.heading('symbol', text='代码')
        self.futures_tree.heading('name', text='名称')
        self.futures_tree.heading('price', text='现价')
        self.futures_tree.heading('change_amount', text='涨跌额')
        self.futures_tree.heading('change', text='涨跌幅')
        self.futures_tree.heading('high', text='高')
        self.futures_tree.heading('low', text='低')

        self.futures_tree.column('symbol', width=72, minwidth=68, anchor='center')
        self.futures_tree.column('name', width=82, minwidth=70, anchor='center')
        self.futures_tree.column('price', width=76, minwidth=64, anchor='e')
        self.futures_tree.column('change_amount', width=70, minwidth=60, anchor='e')
        self.futures_tree.column('change', width=68, minwidth=60, anchor='e')
        self.futures_tree.column('high', width=76, minwidth=64, anchor='e')
        self.futures_tree.column('low', width=76, minwidth=64, anchor='e')

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.futures_tree.yview)
        self.futures_tree.configure(yscrollcommand=scrollbar.set)

        self.futures_tree.tag_configure('up', foreground='#E74C3C')
        self.futures_tree.tag_configure('down', foreground='#27AE60')
        self.futures_tree.tag_configure('flat', foreground='#666666')

        self.futures_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.futures_tree.bind('<Double-1>', self.on_futures_double_click)

        bottom_frame = ttk.Frame(self)
        bottom_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        bottom_frame.columnconfigure(1, weight=1)

        ttk.Label(bottom_frame, text="数据源: 新浪海外期货（免费）").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            bottom_frame,
            text="前台: 10秒",
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=0, column=2, sticky=tk.E)

        self.update_time_var = tk.StringVar(value="最后更新: --:--:--")
        ttk.Label(
            bottom_frame,
            textvariable=self.update_time_var,
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            bottom_frame,
            textvariable=self.status_var,
            font=('Arial', 8),
            foreground='gray'
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        self.refresh_futures_list()

    def _fetch_sina_quotes(self):
        symbols = ','.join(item['quote_symbol'] for item in self.futures.values())
        url = f"https://hq.sinajs.cn/list={symbols}"
        response = requests.get(
            url,
            headers=self._sina_headers(),
            proxies=self.proxies,
            timeout=self.request_timeout
        )
        content = response.content.decode('gb18030', errors='ignore')
        matches = re.findall(r'hq_str_(\w+)="([^"]*)"', content)
        return dict(matches)

    def _build_quote_record(self, symbol, item, raw_quote):
        parts = raw_quote.split(',')
        if len(parts) < 14:
            return None

        price = self._to_float(parts[0])
        if price is None:
            return None

        previous_close = self._to_float(parts[7])
        if previous_close is None:
            previous_close = self._to_float(parts[8])
        if previous_close is None:
            previous_close = price

        change_amount = price - previous_close
        change = (change_amount / previous_close * 100) if previous_close else 0

        return {
            'symbol': symbol,
            'name': item.get('name', symbol),
            'price': price,
            'change_amount': change_amount,
            'change': change,
            'previous_close': previous_close,
            'open': self._to_float(parts[8], previous_close),
            'high': self._to_float(parts[4], price),
            'low': self._to_float(parts[5], price),
            'session': '24H',
            'raw_session': 'GLOBAL_FUTURES',
            'time': f"{parts[12]} {parts[6]}".strip(),
            'source': '新浪海外期货',
        }

    def refresh_futures_list(self):
        for item in self.futures_tree.get_children():
            self.futures_tree.delete(item)

        for symbol, item in self.futures.items():
            if symbol in self.stock_data:
                data = self.stock_data[symbol]
                price_str = self._format_price(data.get('price'))
                change_amount = data.get('change_amount') or 0
                change = data.get('change') or 0
                change_amount_str = f"{change_amount:+.2f}"
                change_str = f"{change:+.2f}%"
                high_str = self._format_price(data.get('high'))
                low_str = self._format_price(data.get('low'))

                if change > 0:
                    tag = 'up'
                elif change < 0:
                    tag = 'down'
                else:
                    tag = 'flat'

                self.futures_tree.insert(
                    '',
                    'end',
                    values=(symbol, item.get('name', symbol), price_str, change_amount_str, change_str, high_str, low_str),
                    tags=(tag,)
                )
            else:
                self.futures_tree.insert(
                    '',
                    'end',
                    values=(symbol, item.get('name', symbol), '--', '--', '--', '--', '--'),
                    tags=('flat',)
                )

    def _refresh_prices_once(self):
        try:
            quotes = self._fetch_sina_quotes()
        except Exception as e:
            print(f"新浪期货请求失败: {e}")
            quotes = {}

        success_count = 0
        for symbol, item in self.futures.items():
            raw_quote = quotes.get(item['quote_symbol'])
            data = self._build_quote_record(symbol, item, raw_quote) if raw_quote else None
            if data:
                self.stock_data[symbol] = data
                success_count += 1

        self.after(0, self.refresh_futures_list)
        current_time = time.strftime("%H:%M:%S")
        self.after(0, lambda t=current_time: self.update_time_var.set(f"最后更新: {t}"))
        if success_count:
            self.after(0, lambda s=success_count: self.status_var.set(f"更新成功: {s}/{len(self.futures)}"))
        else:
            self.after(0, lambda: self.status_var.set("所有数据源失败"))
        return success_count

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
                self.after(0, lambda err=str(e): self.status_var.set(f"更新错误: {err}"))
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
            self.after(0, lambda err=str(e): self.status_var.set(f"刷新失败: {err}"))
        finally:
            self.update_lock.release()

    def on_futures_double_click(self, event=None):
        item_id = self.futures_tree.identify_row(event.y) if event else None
        if not item_id:
            selection = self.futures_tree.selection()
            if not selection:
                return
            item_id = selection[0]
        values = self.futures_tree.item(item_id, 'values')
        if not values:
            return
        symbol = values[0]
        self.show_futures_chart(symbol)

    def _parse_timestamp(self, text):
        if not text:
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                pass
        return None

    def _fetch_intraday_series(self, chart_symbol):
        url = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_data=/GlobalFuturesService.getGlobalFuturesMinLine"
        response = requests.get(
            url,
            params={'symbol': chart_symbol},
            headers=self._sina_headers(),
            proxies=self.proxies,
            timeout=self.request_timeout
        )
        content = response.content.decode('gbk', errors='ignore')
        data = self._extract_jsonp(content)
        rows = data.get('minLine_1d') if isinstance(data, dict) else None
        if not rows:
            return []

        points = []
        today = dt.date.today()
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue

            price = None
            ts_text = ''
            if len(row) >= 10:
                price = self._to_float(row[5])
                ts_text = str(row[9] or '').strip()
                if not ts_text and row[0] and row[4]:
                    ts_text = f"{row[0]} {row[4]}"
                elif not ts_text and row[0]:
                    ts_text = str(row[0]).strip()
            elif len(row) >= 6:
                price = self._to_float(row[1])
                ts_text = str(row[0] or '').strip()
                if len(ts_text) <= 5:
                    ts_text = f"{today.isoformat()} {ts_text}"
            else:
                continue

            if price is None:
                continue

            timestamp = self._parse_timestamp(ts_text)
            if timestamp is None:
                continue
            points.append((timestamp, price))

        points.sort(key=lambda item: item[0])
        return points

    def show_futures_chart(self, symbol):
        item = self._symbol_item(symbol)
        if self.chart_window and self.chart_window.winfo_exists():
            self._close_chart_window()

        window = tk.Toplevel(self.winfo_toplevel())
        window.title(f"{symbol} - {item.get('name', symbol)}")
        window.geometry("980x620")
        window.transient(self.winfo_toplevel())
        window.attributes('-alpha', self.app.alpha)
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_chart_window(window))

        self.chart_window = window
        self.chart_context = {
            'window': window,
            'symbol': symbol,
            'item': item,
            'chart_symbol': item.get('chart_symbol', symbol),
            'refresh_in_progress': False,
        }

        frame = ttk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        top_frame = ttk.Frame(frame)
        top_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        top_frame.columnconfigure(0, weight=1)

        self.chart_info_var = tk.StringVar(value="加载中...")
        ttk.Label(top_frame, textvariable=self.chart_info_var, font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(top_frame, text="刷新", command=lambda: self._fetch_chart_data_async(symbol)).grid(row=0, column=1, sticky=tk.E)

        self.chart_message_var = tk.StringVar(value="")
        ttk.Label(top_frame, textvariable=self.chart_message_var, foreground='gray').grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        self.chart_canvas_holder = ttk.Frame(frame)
        self.chart_canvas_holder.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        self.chart_canvas_holder.columnconfigure(0, weight=1)
        self.chart_canvas_holder.rowconfigure(0, weight=1)

        self._fetch_chart_data_async(symbol)

    def _close_chart_window(self, window=None):
        if self.chart_refresh_job and self.chart_window and self.chart_window.winfo_exists():
            try:
                self.chart_window.after_cancel(self.chart_refresh_job)
            except tk.TclError:
                pass
        self.chart_refresh_job = None

        if window is None:
            window = self.chart_window

        if self.chart_window is window:
            self.chart_window = None
            self.chart_context = None

        try:
            if window:
                window.destroy()
        except Exception:
            pass

    def _schedule_chart_refresh(self):
        context = self.chart_context
        if not context:
            return
        window = context.get('window')
        if not window or not window.winfo_exists():
            return

        if self.chart_refresh_job:
            try:
                window.after_cancel(self.chart_refresh_job)
            except tk.TclError:
                pass

        self.chart_refresh_job = window.after(
            self.chart_refresh_interval_ms,
            lambda: self._fetch_chart_data_async(context['symbol'])
        )

    def _fetch_chart_data_async(self, symbol):
        context = self.chart_context
        if not context or context.get('symbol') != symbol:
            return

        window = context.get('window')
        if not window or not window.winfo_exists():
            return
        if context.get('refresh_in_progress'):
            return

        context['refresh_in_progress'] = True
        chart_symbol = context.get('chart_symbol')
        snapshot = dict(self.stock_data.get(symbol, {}))

        def worker():
            error = None
            points = []
            try:
                points = self._fetch_intraday_series(chart_symbol)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._apply_chart_data(symbol, snapshot, points, error))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_chart_data(self, symbol, snapshot, points, error=None):
        context = self.chart_context
        if not context or context.get('symbol') != symbol:
            return
        window = context.get('window')
        if not window or not window.winfo_exists():
            return

        try:
            for child in self.chart_canvas_holder.winfo_children():
                child.destroy()

            fig = Figure(figsize=(9, 5.6), dpi=100)
            ax = fig.add_subplot(111)
            ax.set_facecolor('#fbfcff')
            ax.grid(True, color='#edf1f7', linewidth=0.8)
            ax.tick_params(axis='both', colors='#6b7280', labelsize=8, length=0)
            ax.spines['left'].set_visible(False)
            for side in ('top', 'right', 'bottom'):
                ax.spines[side].set_color('#d8dee9')
                ax.spines[side].set_linewidth(0.8)
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position('right')

            item = self._symbol_item(symbol)
            if points:
                dates = [point[0] for point in points]
                values = [point[1] for point in points]
                ax.plot(dates, values, color='#246bfe', linewidth=1.5)
                ax.fill_between(dates, values, [min(values)] * len(values), color='#246bfe', alpha=0.08)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                fig.autofmt_xdate()
                latest_price = values[-1]
                previous_close = self._to_float(snapshot.get('previous_close'), values[0])
                if previous_close is None:
                    previous_close = values[0]
                change_amount = latest_price - previous_close if previous_close else 0
                change = (change_amount / previous_close * 100) if previous_close else 0
                self.chart_message_var.set(f"24H 最新价 {self._format_price(latest_price)}")
            else:
                latest_price = self._to_float(snapshot.get('price'))
                change_amount = self._to_float(snapshot.get('change_amount'), 0)
                change = self._to_float(snapshot.get('change'), 0)
                ax.text(
                    0.5, 0.5, '暂无可用 24H 数据',
                    ha='center', va='center', transform=ax.transAxes, color='#8a94a6'
                )
                if error:
                    self.chart_message_var.set('历史数据暂不可用')
                else:
                    self.chart_message_var.set('历史数据暂不可用')

            ax.set_title(f"{symbol} 24H走势", fontsize=11)
            ax.set_ylabel('USD')

            canvas = FigureCanvasTkAgg(fig, master=self.chart_canvas_holder)
            canvas.get_tk_widget().grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            canvas.draw_idle()
            self.chart_canvas = canvas
            self.chart_figure = fig

            self.chart_info_var.set(
                f"{symbol} 现价 {self._format_price(snapshot.get('price') if snapshot else latest_price)}  "
                f"涨跌 {change_amount:+.2f} / {change:+.2f}%  "
                f"高 {self._format_price(snapshot.get('high'))}  低 {self._format_price(snapshot.get('low'))}"
            )
        finally:
            context['refresh_in_progress'] = False
            if window and window.winfo_exists():
                self._schedule_chart_refresh()
