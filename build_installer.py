#!/usr/bin/env python3
"""Build the app executable and the installer executable."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "行情看板"
SETUP_NAME = "行情看板安装包"
ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "installer_payload"
CONFIG_FILES = ("config.json", "stocks.json", "us_stocks.json", "crypto.json")


def run(command):
    print(">", " ".join(str(part) for part in command))
    subprocess.run(command, cwd=ROOT, check=True)


def remove_path(path):
    path = path.resolve()
    if path == ROOT or ROOT not in path.parents:
        raise RuntimeError(f"拒绝清理工作区外路径: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main():
    for path in (
        ROOT / "build",
        ROOT / "dist",
        PAYLOAD,
        ROOT / f"{APP_NAME}.spec",
        ROOT / f"{SETUP_NAME}.spec",
    ):
        remove_path(path)

    add_data = [f"{file_name}{os.pathsep}." for file_name in CONFIG_FILES if (ROOT / file_name).exists()]

    app_command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        APP_NAME,
    ]
    for item in add_data:
        app_command.extend(["--add-data", item])
    app_command.append("main.py")
    run(app_command)

    PAYLOAD.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dist" / f"{APP_NAME}.exe", PAYLOAD / f"{APP_NAME}.exe")
    for file_name in CONFIG_FILES:
        source = ROOT / file_name
        if source.exists():
            shutil.copy2(source, PAYLOAD / file_name)

    installer_command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        SETUP_NAME,
        "--add-data",
        f"{PAYLOAD}{os.pathsep}payload",
        "installer.py",
    ]
    run(installer_command)

    print()
    print(f"构建完成: {ROOT / 'dist' / f'{SETUP_NAME}.exe'}")


if __name__ == "__main__":
    main()
