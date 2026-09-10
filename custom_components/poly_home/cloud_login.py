"""保利智家云端接口：手机号 + 验证码换本地网关所需凭据。

信封与加密来自 APK 逆向（见 docs/PROTOCOL.md）：
- 请求头 method/tid/nonce/appkey/timestamp/signType/version/isEncrypt/encryptType，登录后带 token
- sign = md5(按 key 字典序拼 `k=v&...` + app_secret)
- POST 体是 base64(hex(AES-256-ECB(json)))；GET 的 data 直接放 hex，不套 base64
- 响应 data 是 base64(hex(AES-256-ECB(json)))
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
import uuid
from typing import Any

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from .const import DEFAULT_APP_KEY, DEFAULT_APP_SECRET, DEFAULT_OEM_FIRM

GATEWAY_URL = "https://polysh.unisiot.com/gateway"
AREA_CODE = "86"
APP_MODEL = "HomeAssistant"
TIMEOUT = 20

# 只有家庭列表走 GET，data 拼在查询串里且不套 base64
_QUERY_METHODS = {"smallSmarthome.home.listHomeSn"}

CODE_EXPIRED_VERIFY = 280103
CODE_BAD_VERIFY = 280104
CODE_SEND_LIMIT = 280116


class CloudError(Exception):
    """云端返回失败。code 是云端错误码，取不到时为 None。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def new_session_id() -> str:
    """App 首次启动时本地生成的 si，注册前先用它。"""
    return "android" + hashlib.md5(uuid.uuid4().hex.encode()).hexdigest()[:16]


def _key() -> bytes:
    return DEFAULT_APP_SECRET.encode()[:32].ljust(32, b"\x00")


def _encrypt(text: str, *, raw_hex: bool) -> str:
    blob = binascii.hexlify(AES.new(_key(), AES.MODE_ECB).encrypt(pad(text.encode(), 16)))
    return blob.decode() if raw_hex else base64.b64encode(blob).decode()


def _decrypt(data: str) -> Any:
    raw = AES.new(_key(), AES.MODE_ECB).decrypt(binascii.unhexlify(base64.b64decode(data)))
    return json.loads(unpad(raw, 16).decode())


def _call(method: str, params: dict[str, Any], session_id: str, token: str = "") -> Any:
    query = method in _QUERY_METHODS
    headers = {
        "method": method,
        "tid": session_id,
        "nonce": "11111",
        "appkey": DEFAULT_APP_KEY,
        "timestamp": str(int(time.time() * 1000)),
        "signType": "md5",
        "version": "1.0",
        "isEncrypt": "true",
        "encryptType": "AES",
    }
    if token:
        headers["token"] = token
    headers["data"] = _encrypt(
        json.dumps(params, separators=(",", ":"), ensure_ascii=False), raw_hex=query
    )
    signing = "&".join(f"{name}={headers[name]}" for name in sorted(headers))
    headers["sign"] = hashlib.md5((signing + DEFAULT_APP_SECRET).encode()).hexdigest()

    if query:
        response = requests.get(
            GATEWAY_URL, params=headers, headers={"method": method}, timeout=TIMEOUT
        )
    else:
        body = headers.pop("data")
        headers["Content-Type"] = "application/json; charset=utf-8"
        response = requests.post(GATEWAY_URL, headers=headers, data=body.encode(), timeout=TIMEOUT)

    try:
        payload = response.json()
    except ValueError as err:
        raise CloudError(f"云端返回不是 JSON（HTTP {response.status_code}）") from err
    if payload.get("code") != 0:
        raise CloudError(payload.get("desc") or "云端返回失败", payload.get("code"))
    data = payload.get("data")
    if isinstance(data, str):
        return _decrypt(data) if data not in ("", "null") else {}
    return data or {}


def send_code(phone: str) -> None:
    """给手机号发登录验证码。"""
    _call(
        "app.user.verifyCode",
        {"areaCode": AREA_CODE, "username": phone, "oemFirm": DEFAULT_OEM_FIRM, "type": "login"},
        new_session_id(),
    )


def login(phone: str, code: str, session_id: str) -> dict[str, Any]:
    """用验证码换登录态，返回 token / userUnique。"""
    return _call(
        "app.login.verifyCode",
        {
            "areaCode": AREA_CODE,
            "username": phone,
            "verifyCode": code,
            "si": session_id,
            "locations": "",
            "loginAddress": "",
            "appLanguage": "ZH_CN",
            "oemFirm": DEFAULT_OEM_FIRM,
            "appModel": APP_MODEL,
        },
        session_id,
    )


def register_session(session_id: str, token: str = "") -> str:
    """把本地 si 换成云端签发的 si。App 启动时也是未登录就注册。"""
    data = _call(
        "backdevice.si.register",
        {
            "appDevice": "phone",
            "appImei": "",
            "appMac": "",
            "appModel": APP_MODEL,
            "appPackage": "com.poly.smarthome.pro",
            "appSys": "android",
            "appVer": "5.06.002",
            "sysVer": "",
            "clientType": "poly_app",
            "oemFirm": DEFAULT_OEM_FIRM,
            "resolvingPower": "",
        },
        session_id,
        token,
    )
    return data["si"]


def list_homes(token: str, session_id: str) -> list[dict[str, Any]]:
    """账号下的家庭列表，含网关 sn、局域网地址。"""
    data = _call(
        "smallSmarthome.home.listHomeSn",
        {"token": token, "appType": "tgwApp"},
        session_id,
        token,
    )
    return data if isinstance(data, list) else data.get("homeList") or []


