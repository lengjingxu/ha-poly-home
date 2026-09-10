#!/usr/bin/env python3
"""从已登录的保利智家 App（模拟器/root 真机）提取服务所需凭据。

用法: python3 extract_credentials.py [--serial <adb-serial>]
产出:
  - config.json    用户级凭据 + 网关地址（chmod 600，已 gitignore）
  - secrets.env    APP_SECRET 一行（chmod 600，已 gitignore；值来自 APK 逆向，
                   服务端启动时读取，不进代码仓库）

用户级凭据说明（均在 App SharedPreferences 中）:
  host_sn       网关序列号（topic/请求必需）
  gateway_ip    网关局域网 IP（DHCP 可能变化，需定期核对路由器）
  login_token   云端会话令牌（核心鉴权，App 登录时下发，会过期）
  uniqkey       userUnique（用户 ID，控制命令必需）
  APP_SI        si（App 设备标识）
"""
import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

PKG = "com.poly.smarthome.pro"
PREFS_DIR = f"/data/data/{PKG}/shared_prefs"

# 全部 prefs XML 中按 key 采集；key -> 配置项名
KEY_MAP = {
    "host_sn": "host_sn",
    "host_ip": "gateway_ip",
    "login_token": "login_token",
    "uniqkey": "user_unique",
    "APP_SI": "si",
    "home_id": "home_id",
}

# APK 逆向所得的 App 级常量（除 app_secret 外可随代码分发）
APP_CONSTANTS = {
    "app_key": "0e71bdeec1089eff",
    "oem": "0X8601",
    "client_type": "poly_app",
    "mqtt_port": 1883,
}

REQUIRED = ("host_sn", "login_token", "user_unique", "si")


def adb(serial, *args):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def list_prefs_files(serial):
    r = adb(serial, "shell", f"su root ls {PREFS_DIR}")
    if r.returncode != 0:
        sys.exit(f"列出 shared_prefs 失败: {r.stderr.strip()}")
    return [f.strip() for f in r.stdout.splitlines() if f.strip().endswith(".xml")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", help="adb 设备序列号（多设备时必填）")
    ap.add_argument("--app-secret", help="APK 逆向所得 app_secret（也可用环境变量 POLY_APP_SECRET）")
    args = ap.parse_args()

    cfg = dict(APP_CONSTANTS)
    found_sources = {}

    for fname in list_prefs_files(args.serial):
        r = adb(args.serial, "shell", f"su root cat {PREFS_DIR}/{fname}")
        if r.returncode != 0 or "<map>" not in r.stdout:
            continue
        root = ET.fromstring(r.stdout)
        for elem in root:
            name = elem.get("name")
            if name in KEY_MAP:
                value = elem.get("value") or (elem.text or "")
                if value and KEY_MAP[name] not in cfg:
                    cfg[KEY_MAP[name]] = value
                    found_sources[KEY_MAP[name]] = fname

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        sys.exit(f"缺少凭据（App 可能未登录）: {missing}")

    cfg["gateway_host"] = f'{cfg.get("gateway_ip", "192.168.1.2")}:{cfg["mqtt_port"]}'

    # 用户级凭据 -> config.json
    with open("config.json", "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    import os

    os.chmod("config.json", 0o600)

    # app_secret -> secrets.env（逆向所得的 App 级密钥，与用户凭据隔离）
    secret = read_app_secret(args.app_secret)
    with open("secrets.env", "w") as f:
        f.write(f"POLY_APP_SECRET={secret}\n")
    os.chmod("secrets.env", 0o600)

    print("已写入 config.json / secrets.env（均 chmod 600）")
    for k, src in found_sources.items():
        print(f"  {k} <- {PREFS_DIR}/{src}")
    print(f"  gateway: {cfg['gateway_host']}")
    print(f"  login_token: {cfg['login_token'][:8]}...（{len(cfg['login_token'])} 字符）")


def read_app_secret(cli_value) -> str:
    """app_secret 来源优先级：--app-secret 参数 > 环境变量 POLY_APP_SECRET。
    值本身来自 APK 逆向（Frida 调 cc.a.a()），不硬编码在仓库源码中。"""
    import os

    if cli_value:
        return cli_value.strip()
    env_secret = os.environ.get("POLY_APP_SECRET", "").strip()
    if env_secret:
        return env_secret
    sys.exit(
        "缺少 app_secret：请设置环境变量 POLY_APP_SECRET（值可从运行中的 App 用 Frida 获取：\n"
        "  frida -U -n 'Poly Smart Home' 后执行 Java.use('cc.a').a() ）"
    )


if __name__ == "__main__":
    main()
