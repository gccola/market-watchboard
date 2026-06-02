#!/usr/bin/env python3
"""Installer for the market ticker desktop app."""

import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "行情看板"
EXE_NAME = f"{APP_NAME}.exe"
PAYLOAD_DIR = "payload"
CONFIG_FILES = ("config.json", "stocks.json", "crypto.json")


def resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def vbs_quote(value):
    return str(value).replace('"', '""')


class Installer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} - 安装程序")
        self.root.geometry("560x390")
        self.root.resizable(False, False)

        default_base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        self.install_path = tk.StringVar(value=os.path.join(default_base, APP_NAME))
        self.desktop_shortcut = tk.BooleanVar(value=True)
        self.start_menu_shortcut = tk.BooleanVar(value=True)

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=22)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main_frame,
            text=f"{APP_NAME} 安装程序",
            font=("Microsoft YaHei", 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 18))

        ttk.Label(
            main_frame,
            text="请选择安装位置:",
            font=("Microsoft YaHei", 10),
        ).pack(anchor=tk.W)

        path_frame = ttk.Frame(main_frame)
        path_frame.pack(fill=tk.X, pady=(6, 14))

        ttk.Entry(path_frame, textvariable=self.install_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(path_frame, text="浏览...", command=self.browse_path).pack(
            side=tk.LEFT, padx=(10, 0)
        )

        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=(0, 16))
        ttk.Checkbutton(
            options_frame,
            text="创建桌面快捷方式",
            variable=self.desktop_shortcut,
        ).pack(anchor=tk.W)
        ttk.Checkbutton(
            options_frame,
            text="创建开始菜单快捷方式",
            variable=self.start_menu_shortcut,
        ).pack(anchor=tk.W, pady=(4, 0))

        info = (
            "安装内容:\n"
            f"- {APP_NAME} 主程序\n"
            "- A股行情和加密行情模块\n"
            "- 默认配置文件和卸载脚本"
        )
        ttk.Label(main_frame, text=info, foreground="#666666").pack(
            anchor=tk.W, pady=(0, 16)
        )

        self.progress = ttk.Progressbar(main_frame, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, pady=(0, 18))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="安装", command=self.install, width=14).pack(
            side=tk.RIGHT, padx=(10, 0)
        )
        ttk.Button(button_frame, text="取消", command=self.root.destroy, width=14).pack(
            side=tk.RIGHT
        )

    def browse_path(self):
        path = filedialog.askdirectory(title="选择安装位置")
        if path:
            self.install_path.set(os.path.join(path, APP_NAME))

    def payload_path(self):
        return os.path.join(resource_dir(), PAYLOAD_DIR)

    def install(self):
        install_dir = os.path.abspath(self.install_path.get().strip())
        if not install_dir:
            messagebox.showerror("错误", "请选择安装位置")
            return

        payload_dir = self.payload_path()
        app_exe = os.path.join(payload_dir, EXE_NAME)
        if not os.path.exists(app_exe):
            messagebox.showerror(
                "错误",
                f"安装包不完整，未找到主程序:\n{app_exe}",
            )
            return

        try:
            if os.path.exists(install_dir):
                ok = messagebox.askyesno(
                    "确认",
                    "安装目录已存在。继续安装会覆盖主程序，但保留已有配置文件。\n\n是否继续？",
                )
                if not ok:
                    return

            os.makedirs(install_dir, exist_ok=True)
            self.progress.configure(value=15)
            self.root.update_idletasks()

            shutil.copy2(app_exe, os.path.join(install_dir, EXE_NAME))
            self.progress.configure(value=40)
            self.root.update_idletasks()

            for file_name in CONFIG_FILES:
                source = os.path.join(payload_dir, file_name)
                target = os.path.join(install_dir, file_name)
                if os.path.exists(source) and not os.path.exists(target):
                    shutil.copy2(source, target)

            self.create_uninstaller(install_dir)
            self.progress.configure(value=65)
            self.root.update_idletasks()

            if self.desktop_shortcut.get():
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                self.create_shortcut(
                    os.path.join(desktop, f"{APP_NAME}.lnk"),
                    os.path.join(install_dir, EXE_NAME),
                    install_dir,
                )

            if self.start_menu_shortcut.get():
                start_menu = os.path.join(
                    os.environ.get("APPDATA", os.path.expanduser("~")),
                    "Microsoft",
                    "Windows",
                    "Start Menu",
                    "Programs",
                    APP_NAME,
                )
                os.makedirs(start_menu, exist_ok=True)
                self.create_shortcut(
                    os.path.join(start_menu, f"{APP_NAME}.lnk"),
                    os.path.join(install_dir, EXE_NAME),
                    install_dir,
                )

            self.progress.configure(value=100)
            messagebox.showinfo(
                "安装完成",
                f"{APP_NAME} 已安装到:\n{install_dir}",
            )
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("安装失败", f"安装过程中出现错误:\n{e}")

    def create_shortcut(self, shortcut_path, target_path, working_dir):
        script = f'''Set shell = CreateObject("WScript.Shell")
Set shortcut = shell.CreateShortcut("{vbs_quote(shortcut_path)}")
shortcut.TargetPath = "{vbs_quote(target_path)}"
shortcut.WorkingDirectory = "{vbs_quote(working_dir)}"
shortcut.IconLocation = "{vbs_quote(target_path)},0"
shortcut.Save
'''
        fd, script_path = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.run(["cscript", "//nologo", script_path], check=True, capture_output=True)
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

    def create_uninstaller(self, install_dir):
        desktop_link = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
        start_menu_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            APP_NAME,
        )
        script = f'''@echo off
chcp 65001 >nul
echo 正在卸载 {APP_NAME}...
taskkill /im "{EXE_NAME}" /f >nul 2>nul
del /f /q "{desktop_link}" >nul 2>nul
rd /s /q "{start_menu_dir}" >nul 2>nul
cd /d "%TEMP%"
timeout /t 1 /nobreak >nul
rd /s /q "{install_dir}" >nul 2>nul
echo 卸载完成。
pause
'''
        with open(os.path.join(install_dir, "uninstall.bat"), "w", encoding="utf-8") as f:
            f.write(script)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Installer().run()
