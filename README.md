# 行情看板

Windows 桌面行情看板，支持 A 股、美股/ETF、期货和加密货币。界面基于 Tkinter，走势图使用 Matplotlib。

## 功能

- A 股行情列表：现价、涨跌额、涨跌幅、换手率
- 双击 A 股查看分时走势、日 K 线、成交额和 MACD
- 美股行情页：支持搜索添加美股、ETF，也内置纽约黄金期货
- 美股/ETF 支持盘前、盘中、盘后行情展示，黄金期货支持夜盘/近全天行情
- 双击美股/ETF/黄金期货查看分时走势、日 K 线和 MACD
- 期货页：查看 XAUUSD、XAGUSD、CLMAIN 的实时/24H 行情
- 图表支持大十字光标，查看具体分时点或 K 线数据
- 支持透明度设置
- 支持加密货币行情页
- 支持生成独立 exe 和安装包

## 美股数据源

- 美股/ETF 盘前、盘中、盘后报价、搜索、分时和日 K：优先使用 Nasdaq 公共接口
- 美股/ETF 夜盘报价：可选 Alpaca overnight 数据源，需配置 API Key
- 黄金期货：优先使用新浪外盘期货接口，默认标的是 `hf_GC` / `GC`
- CNBC 作为美股/ETF/期货报价备用源
- 免费公开接口可能存在可用性和频率限制；未配置 Alpaca 夜盘源时，夜盘会标记为 `夜盘无源`

## 期货数据源

期货页使用新浪海外期货免费接口，无需配置 Key：

- `XAUUSD` -> `hf_GC` / `GC`
- `XAGUSD` -> `hf_SI` / `SI`
- `CLMAIN` -> `hf_CL` / `CL`

它提供 24H 实时报价和 24H 分时走势，适合看连续行情。

## Alpaca 夜盘配置

美股/ETF 的真实夜盘报价需要第三方行情权限。程序支持 Alpaca overnight feed，配置以下任一组环境变量后，夜盘时会自动优先尝试：

```powershell
$env:APCA_API_KEY_ID="你的 Alpaca API Key"
$env:APCA_API_SECRET_KEY="你的 Alpaca Secret Key"
python main.py
```

也可以使用：

```powershell
$env:ALPACA_API_KEY="你的 Alpaca API Key"
$env:ALPACA_API_SECRET="你的 Alpaca Secret Key"
python main.py
```

未配置 Key 时，程序不会伪造夜盘价，会回退到 Nasdaq/CNBC 的常规或延时数据。

## 运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

首次运行也可以直接双击：

```text
run.bat
```

`run.bat` 会先安装依赖，再用 `pythonw main.py` 启动程序。

## 打包

双击：

```text
build.bat
```

或者手动执行：

```powershell
python build_installer.py
```

完成后会生成：

- `dist/行情看板.exe`
- `dist/行情看板安装包.exe`

`dist/` 是构建产物，已在 `.gitignore` 中排除。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `main.py` | 程序入口 |
| `a_stock_tab.py` | A 股行情页和走势图 |
| `us_stock_tab.py` | 美股、ETF、黄金期货行情页和走势图 |
| `futures_tab.py` | 期货行情页 |
| `crypto_tab.py` | 加密货币行情页 |
| `run.bat` | 安装依赖并启动程序 |
| `run.vbs` | 静默启动程序 |
| `setup.bat` | 打开安装包，不存在时先构建 |
| `build.bat` | 安装打包依赖并构建安装包 |
| `build_installer.py` | PyInstaller 打包脚本 |
| `installer.py` | 安装包程序 |
| `config.json` | 主程序配置 |
| `stocks.json` | A 股自选列表 |
| `us_stocks.json` | 美股/ETF/黄金期货自选列表 |
| `crypto.json` | 加密货币自选列表 |
