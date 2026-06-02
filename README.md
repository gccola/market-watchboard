# 行情看板

Windows 桌面行情看板，支持 A 股与加密货币行情查看。界面基于 Tkinter，走势图使用 Matplotlib 绘制。

## 功能

- A 股行情列表：现价、涨跌额、涨跌幅、换手率
- 双击 A 股查看分时走势、日 K 线、成交额和 MACD
- 图表支持大十字光标，查看具体分时点或 K 线数据
- 支持透明度设置
- 支持加密货币行情页
- 支持生成独立 exe 和安装包

## 一键运行

首次运行建议直接双击：

```text
run.bat
```

`run.bat` 会先安装 `requirements.txt` 中的依赖，然后用 `pythonw main.py` 启动程序。

如果依赖已经安装好，想静默启动、不显示命令行窗口，可以双击：

```text
run.vbs
```

`run.vbs` 只负责静默运行 `pythonw main.py`，不会自动安装依赖。

## 手动运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 生成安装包

双击：

```text
build.bat
```

或手动执行：

```powershell
python build_installer.py
```

打包完成后会生成：

```text
dist/行情看板.exe
dist/行情看板安装包.exe
```

`dist/` 是构建产物，已在 `.gitignore` 中排除，不提交到 GitHub。

## 一键安装

双击：

```text
setup.bat
```

如果 `dist/行情看板安装包.exe` 已存在，`setup.bat` 会直接打开安装包；如果不存在，会先调用 `build.bat` 构建。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `main.py` | 程序入口 |
| `a_stock_tab.py` | A 股行情页和走势图 |
| `crypto_tab.py` | 加密货币行情页 |
| `run.bat` | 安装依赖并启动程序 |
| `run.vbs` | 静默启动程序 |
| `setup.bat` | 打开安装包，不存在时先构建 |
| `build.bat` | 安装打包依赖并构建安装包 |
| `build_installer.py` | PyInstaller 打包脚本 |
| `installer.py` | 安装包程序 |
| `config.json` | 主程序配置 |
| `stocks.json` | A 股自选列表 |
| `crypto.json` | 加密货币自选列表 |

## 环境要求

- Windows
- Python 3.10 或更高版本
- 网络访问腾讯/新浪/东方财富等行情接口
