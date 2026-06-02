#!/usr/bin/env python3
"""
加密行情选项卡模块
支持添加/删除币种、实时价格更新、多数据源切换
"""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import time
import threading
import os
import sys


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class CryptoFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        
        self.proxies = self.get_system_proxies()
        self.config_file = os.path.join(get_app_dir(), 'crypto.json')
        self.cryptos = self.load_cryptos()
        self.crypto_data = {}
        
        self.data_sources = [
            {
                'name': 'Gate.io',
                'url_template': 'https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={symbol}',
                'symbol_map': {
                    'BTCUSDT': 'BTC_USDT',
                    'ETHUSDT': 'ETH_USDT',
                    'SOLUSDT': 'SOL_USDT',
                    'DOGEUSDT': 'DOGE_USDT',
                    'XRPUSDT': 'XRP_USDT',
                    'BNBUSDT': 'BNB_USDT',
                    'ADAUSDT': 'ADA_USDT',
                    'DOTUSDT': 'DOT_USDT',
                    'AVAXUSDT': 'AVAX_USDT',
                    'LINKUSDT': 'LINK_USDT',
                    'MATICUSDT': 'MATIC_USDT',
                    'UNIUSDT': 'UNI_USDT',
                },
                'parser': lambda data: {
                    'price': float(data[0]['last']),
                    'change_pct': float(data[0].get('change_percentage', 0)),
                    'change_amt': float(data[0]['last']) - float(data[0].get('last_size', 0))
                }
            },
            {
                'name': 'CoinEx',
                'url_template': 'https://api.coinex.com/v1/market/ticker?market={symbol}',
                'symbol_map': {
                    'BTCUSDT': 'BTCUSDT',
                    'ETHUSDT': 'ETHUSDT',
                    'SOLUSDT': 'SOLUSDT',
                    'DOGEUSDT': 'DOGEUSDT',
                    'XRPUSDT': 'XRPUSDT',
                    'BNBUSDT': 'BNBUSDT',
                    'ADAUSDT': 'ADAUSDT',
                    'DOTUSDT': 'DOTUSDT',
                    'AVAXUSDT': 'AVAXUSDT',
                    'LINKUSDT': 'LINKUSDT',
                    'MATICUSDT': 'MATICUSDT',
                    'UNIUSDT': 'UNIUSDT',
                },
                'parser': lambda data: {
                    'price': float(data['data']['ticker']['last']),
                    'change_pct': float(data['data']['ticker'].get('change_percentage', 0)),
                    'change_amt': float(data['data']['ticker']['last']) - float(data['data']['ticker'].get('open', data['data']['ticker']['last']))
                }
            },
            {
                'name': 'Binance Spot',
                'url_template': 'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}',
                'symbol_map': {
                    'BTCUSDT': 'BTCUSDT',
                    'ETHUSDT': 'ETHUSDT',
                    'SOLUSDT': 'SOLUSDT',
                    'DOGEUSDT': 'DOGEUSDT',
                    'XRPUSDT': 'XRPUSDT',
                    'BNBUSDT': 'BNBUSDT',
                    'ADAUSDT': 'ADAUSDT',
                    'DOTUSDT': 'DOTUSDT',
                    'AVAXUSDT': 'AVAXUSDT',
                    'LINKUSDT': 'LINKUSDT',
                    'MATICUSDT': 'MATICUSDT',
                    'UNIUSDT': 'UNIUSDT',
                },
                'parser': lambda data: {
                    'price': float(data['lastPrice']),
                    'change_pct': float(data['priceChangePercent']),
                    'change_amt': float(data['priceChange'])
                }
            },
            {
                'name': 'OKX',
                'url_template': 'https://www.okx.com/api/v5/market/ticker?instId={inst_id}',
                'symbol_map': {
                    'BTCUSDT': 'BTC-USDT-SWAP',
                    'ETHUSDT': 'ETH-USDT-SWAP',
                    'SOLUSDT': 'SOL-USDT-SWAP',
                    'DOGEUSDT': 'DOGE-USDT-SWAP',
                    'XRPUSDT': 'XRP-USDT-SWAP',
                    'BNBUSDT': 'BNB-USDT-SWAP',
                    'ADAUSDT': 'ADA-USDT-SWAP',
                    'DOTUSDT': 'DOT-USDT-SWAP',
                    'AVAXUSDT': 'AVAX-USDT-SWAP',
                    'LINKUSDT': 'LINK-USDT-SWAP',
                    'MATICUSDT': 'MATIC-USDT-SWAP',
                    'UNIUSDT': 'UNI-USDT-SWAP',
                },
                'parser': lambda data: {
                    'price': float(data['data'][0]['last']),
                    'change_pct': float(data['data'][0].get('sodUtc8', 0)) if float(data['data'][0].get('sodUtc8', 0)) != 0 else 0,
                    'change_amt': float(data['data'][0]['last']) - float(data['data'][0].get('sodUtc8', data['data'][0]['last']))
                }
            },
            {
                'name': 'Bybit',
                'url_template': 'https://api.bybit.com/v2/public/tickers?symbol={symbol}',
                'symbol_map': {
                    'BTCUSDT': 'BTCUSDT',
                    'ETHUSDT': 'ETHUSDT',
                    'SOLUSDT': 'SOLUSDT',
                    'DOGEUSDT': 'DOGEUSDT',
                    'XRPUSDT': 'XRPUSDT',
                    'BNBUSDT': 'BNBUSDT',
                    'ADAUSDT': 'ADAUSDT',
                    'DOTUSDT': 'DOTUSDT',
                    'AVAXUSDT': 'AVAXUSDT',
                    'LINKUSDT': 'LINKUSDT',
                    'MATICUSDT': 'MATICUSDT',
                    'UNIUSDT': 'UNIUSDT',
                },
                'parser': lambda data: {
                    'price': float(data['result'][0]['last_price']),
                    'change_pct': float(data['result'][0].get('price_24h_pcnt', 0)),
                    'change_amt': float(data['result'][0]['last_price']) - float(data['result'][0].get('prev_price_24h', data['result'][0]['last_price']))
                }
            },
            {
                'name': 'CoinCap',
                'url_template': 'https://api.coincap.io/v2/assets/{asset}',
                'symbol_map': {
                    'BTCUSDT': 'bitcoin',
                    'ETHUSDT': 'ethereum',
                    'SOLUSDT': 'solana',
                    'DOGEUSDT': 'dogecoin',
                    'XRPUSDT': 'ripple',
                    'BNBUSDT': 'binance-coin',
                    'ADAUSDT': 'cardano',
                    'DOTUSDT': 'polkadot',
                    'AVAXUSDT': 'avalanche',
                    'LINKUSDT': 'chainlink',
                    'MATICUSDT': 'polygon',
                    'UNIUSDT': 'uniswap',
                },
                'parser': lambda data: {
                    'price': float(data['data']['priceUsd']),
                    'change_pct': float(data['data'].get('changePercent24Hr', 0)),
                    'change_amt': float(data['data']['priceUsd']) * float(data['data'].get('changePercent24Hr', 0)) / 100
                }
            }
        ]
        
        self.selected_source = tk.StringVar(value="自动")
        self.source_names = ["自动"] + [source['name'] for source in self.data_sources]
        
        self.running = True
        
        self.create_widgets()
        
        self.update_thread = threading.Thread(target=self.update_prices, daemon=True)
        self.update_thread.start()
    
    def load_cryptos(self):
        default_cryptos = {
            "BTCUSDT": "比特币",
            "ETHUSDT": "以太坊"
        }
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
        return default_cryptos
    
    def save_cryptos(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.cryptos, f, ensure_ascii=False, indent=2)
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
        
        ttk.Label(title_frame, text="加密行情", font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(title_frame, text="+ 添加币种", command=self.show_add_crypto_dialog).grid(row=0, column=2, sticky=tk.E)
        
        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ('symbol', 'name', 'price', 'change_pct')
        self.crypto_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        
        self.crypto_tree.heading('symbol', text='币种')
        self.crypto_tree.heading('name', text='名称')
        self.crypto_tree.heading('price', text='价格(USD)')
        self.crypto_tree.heading('change_pct', text='24h涨跌幅')
        
        self.crypto_tree.column('symbol', width=70, anchor='center')
        self.crypto_tree.column('name', width=60, anchor='center')
        self.crypto_tree.column('price', width=100, anchor='e')
        self.crypto_tree.column('change_pct', width=80, anchor='e')
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.crypto_tree.yview)
        self.crypto_tree.configure(yscrollcommand=scrollbar.set)
        
        self.crypto_tree.tag_configure('up', foreground='#E74C3C')
        self.crypto_tree.tag_configure('down', foreground='#27AE60')
        self.crypto_tree.tag_configure('flat', foreground='#666666')
        
        self.crypto_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        self.crypto_tree.bind('<Button-3>', self.show_context_menu)
        
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="删除币种", command=self.delete_selected_crypto)
        
        bottom_frame = ttk.Frame(self)
        bottom_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        bottom_frame.columnconfigure(1, weight=1)
        
        ttk.Label(bottom_frame, text="数据源:").grid(row=0, column=0, sticky=tk.W)
        source_combo = ttk.Combobox(bottom_frame, textvariable=self.selected_source, 
                                    values=self.source_names, state="readonly", width=12)
        source_combo.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        source_combo.bind("<<ComboboxSelected>>", self.on_source_change)
        
        self.update_time_var = tk.StringVar(value="最后更新: --:--:--")
        ttk.Label(bottom_frame, textvariable=self.update_time_var, 
                 font=('Arial', 8), foreground='gray').grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
        
        ttk.Label(bottom_frame, text="刷新: 1秒", 
                 font=('Arial', 8), foreground='gray').grid(row=1, column=2, sticky=tk.E, pady=(5, 0))
        
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom_frame, textvariable=self.status_var, 
                 font=('Arial', 8), foreground='gray').grid(row=2, column=0, columnspan=3, sticky=tk.W)
        
        btn_frame = ttk.Frame(bottom_frame)
        btn_frame.grid(row=0, column=2, sticky=tk.E, padx=(10, 0))
        
        ttk.Button(btn_frame, text="刷新", command=self.manual_refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="设置", command=self.show_settings).pack(side=tk.LEFT, padx=2)
        
        self.refresh_crypto_list()
    
    def show_add_crypto_dialog(self):
        available_cryptos = {
            "BTCUSDT": "比特币",
            "ETHUSDT": "以太坊",
            "SOLUSDT": "Solana",
            "DOGEUSDT": "狗狗币",
            "XRPUSDT": "瑞波币",
            "BNBUSDT": "BNB",
            "ADAUSDT": "艾达币",
            "DOTUSDT": "波卡",
            "AVAXUSDT": "雪崩",
            "LINKUSDT": "LINK",
            "MATICUSDT": "Polygon",
            "UNIUSDT": "Uniswap",
        }
        
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("添加币种")
        dialog.geometry("350x400")
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()
        
        dialog.update_idletasks()
        x = parent_x - 360
        y = parent_y
        if y + 400 > 900:
            y = 500
        if y < 0:
            y = 0
        dialog.geometry(f"+{x}+{y}")
        dialog.attributes('-alpha', self.app.alpha)
        
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        ttk.Label(dialog, text="选择要添加的币种:", font=('Microsoft YaHei', 10)).pack(pady=(15, 5))
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 5))
        
        listbox = tk.Listbox(list_frame, height=10, font=('Arial', 10))
        listbox.pack(fill=tk.BOTH, expand=True)
        
        available_items = []
        for symbol, name in available_cryptos.items():
            if symbol not in self.cryptos:
                available_items.append((symbol, name))
                listbox.insert(tk.END, f"{symbol} - {name}")
        
        if not available_items:
            listbox.insert(tk.END, "所有币种已添加")
        
        ttk.Label(dialog, text="双击列表项添加币种（可继续添加）", font=('Microsoft YaHei', 8), foreground='gray').pack(pady=(0, 5))
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        def add_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("提示", "请先选择一个币种", parent=dialog)
                return
            
            idx = selection[0]
            if idx < len(available_items):
                symbol, name = available_items[idx]
                self.cryptos[symbol] = name
                self.save_cryptos()
                self.refresh_crypto_list()
                self.status_var.set(f"已添加: {name}")
        
        listbox.bind('<Double-1>', lambda e: add_selected())
        
        ttk.Button(btn_frame, text="添加选中", command=add_selected, width=10).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy, width=10).pack(side=tk.RIGHT)
    
    def delete_selected_crypto(self):
        selection = self.crypto_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        symbol = self.crypto_tree.item(item)['values'][0]
        
        if symbol in self.cryptos:
            name = self.cryptos[symbol]
            del self.cryptos[symbol]
            self.save_cryptos()
            self.refresh_crypto_list()
            self.status_var.set(f"已删除: {name}")
    
    def show_context_menu(self, event):
        item = self.crypto_tree.identify_row(event.y)
        if item:
            self.crypto_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def on_source_change(self, event=None):
        selected = self.selected_source.get()
        if selected == "自动":
            self.status_var.set("数据源: 自动选择")
        else:
            self.status_var.set(f"数据源: {selected}")
    
    def fetch_price_from_source(self, source, symbol):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            mapped_symbol = source['symbol_map'].get(symbol, symbol)
            
            if source.get('is_batch'):
                url = source['url_template'].format(ids=mapped_symbol)
            else:
                url = source['url_template'].format(symbol=mapped_symbol, inst_id=mapped_symbol)
            
            proxies = self.proxies if self.proxies else None
            
            response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return source['parser'](data)
            
        except Exception as e:
            print(f"从{source['name']}获取{symbol}价格失败: {e}")
            return None
    
    def fetch_price(self, symbol):
        selected = self.selected_source.get()
        
        if selected != "自动":
            for source in self.data_sources:
                if source['name'] == selected:
                    price = self.fetch_price_from_source(source, symbol)
                    if price is not None:
                        self.after(0, lambda: self.status_var.set(f"数据源: {source['name']}"))
                        return price
                    else:
                        self.after(0, lambda: self.status_var.set(f"数据源 {selected} 失败"))
                        return None
        
        for source in self.data_sources:
            price = self.fetch_price_from_source(source, symbol)
            if price is not None:
                self.after(0, lambda: self.status_var.set(f"数据源: {source['name']}"))
                return price
        
        self.after(0, lambda: self.status_var.set("所有数据源失败"))
        return None
    
    def refresh_crypto_list(self):
        for item in self.crypto_tree.get_children():
            self.crypto_tree.delete(item)
        
        for symbol, name in self.cryptos.items():
            if symbol in self.crypto_data:
                data = self.crypto_data[symbol]
                price = data['price']
                change_pct = data['change_pct']
                
                price_str = f"${price:,.2f}"
                change_pct_str = f"{change_pct:+.2f}%"
                
                if change_pct > 0:
                    tag = 'up'
                elif change_pct < 0:
                    tag = 'down'
                else:
                    tag = 'flat'
                
                self.crypto_tree.insert('', 'end', values=(symbol, name, price_str, change_pct_str), tags=(tag,))
            else:
                self.crypto_tree.insert('', 'end', values=(symbol, name, "加载中...", "--"), tags=('flat',))
    
    def update_prices(self):
        while self.running:
            try:
                for symbol in list(self.cryptos.keys()):
                    if not self.running:
                        break
                    price = self.fetch_price(symbol)
                    if price is not None:
                        self.crypto_data[symbol] = price
                
                self.after(0, self.refresh_crypto_list)
                
                current_time = time.strftime("%H:%M:%S")
                self.after(0, lambda: self.update_time_var.set(f"最后更新: {current_time}"))
                
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"更新错误: {str(e)}"))
            
            time.sleep(1)
    
    def manual_refresh(self):
        self.status_var.set("正在刷新...")
        threading.Thread(target=self._manual_refresh_thread, daemon=True).start()
    
    def _manual_refresh_thread(self):
        try:
            for symbol in list(self.cryptos.keys()):
                price = self.fetch_price(symbol)
                if price is not None:
                    self.crypto_data[symbol] = price
            
            self.after(0, self.refresh_crypto_list)
            
            current_time = time.strftime("%H:%M:%S")
            self.after(0, lambda: self.update_time_var.set(f"最后更新: {current_time}"))
            self.after(0, lambda: self.status_var.set("手动刷新完成"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"刷新失败: {str(e)}"))
    
    def show_settings(self):
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title("设置")
        dialog.geometry("300x200")
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()
        
        dialog.update_idletasks()
        x = parent_x - 310
        y = parent_y
        if y + 200 > 900:
            y = 700
        if y < 0:
            y = 0
        dialog.geometry(f"+{x}+{y}")
        dialog.attributes('-alpha', self.app.alpha)
        
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        ttk.Label(dialog, text="透明度:").pack(pady=(10, 0))
        alpha_var = tk.DoubleVar(value=self.app.alpha)
        alpha_scale = tk.Scale(dialog, from_=0.3, to=1.0, resolution=0.05,
                              variable=alpha_var, orient=tk.HORIZONTAL,
                              length=200, sliderlength=20,
                              command=lambda v: self.app.set_alpha(float(v)))
        alpha_scale.pack(pady=(0, 10))
        
        current_proxy = ""
        if self.proxies:
            for key in ['http', 'https']:
                if key in self.proxies:
                    current_proxy = self.proxies[key]
                    break
        
        ttk.Label(dialog, text="代理地址:").pack(pady=(0, 5))
        proxy_var = tk.StringVar(value=current_proxy)
        proxy_entry = ttk.Entry(dialog, textvariable=proxy_var, width=35)
        proxy_entry.pack(pady=(0, 10))
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=5)
        
        def apply_settings():
            proxy_url = proxy_var.get().strip()
            if proxy_url:
                self.proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
                self.status_var.set(f"代理已设置: {proxy_url}")
            else:
                self.proxies = None
                self.status_var.set("代理已清除")
            dialog.destroy()
        
        def clear_proxy():
            proxy_var.set("")
            apply_settings()
        
        ttk.Button(button_frame, text="应用", command=apply_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="清除代理", command=clear_proxy).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
