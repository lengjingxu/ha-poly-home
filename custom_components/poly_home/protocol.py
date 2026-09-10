"""保利智家 UIOT MQTT 载荷编解码。

协议来自 APK 逆向，见 poly_smarthome_service/PROTOCOL.md：
- MQTT 认证: username = appKey|si|clientType|毫秒|loginToken，password = MD5(username + appSecret)
- 业务载荷: 78 字节头(UIOT + appKey + MD5 签名 + EOS) + zlib(AES-256-ECB(json))
"""

from __future__ import annotations

import hashlib
import json
import time
import zlib
from collections.abc import Mapping
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_CLIENT_TYPE,
    CONF_GATEWAY_HOST,
    CONF_HOST_SN,
    CONF_LOGIN_TOKEN,
    CONF_SI,
    CONF_USER_UNIQUE,
    DEFAULT_CLIENT_TYPE,
)

HEADER_LEN = 78


class UiotConfig:
    """一次配置条目对应的协议与账号凭据。"""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self.gateway_host: str = data[CONF_GATEWAY_HOST]
        self.app_key: str = data[CONF_APP_KEY]
        self.app_secret: str = data[CONF_APP_SECRET]
        self.host_sn: str = data[CONF_HOST_SN]
        self.si: str = data[CONF_SI]
        self.login_token: str = data[CONF_LOGIN_TOKEN]
        self.user_unique: str = data[CONF_USER_UNIQUE]
        self.client_type: str = data.get(CONF_CLIENT_TYPE) or DEFAULT_CLIENT_TYPE

    @property
    def host(self) -> str:
        return self.gateway_host.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.gateway_host.rsplit(":", 1)[1])

    def mqtt_credentials(self) -> tuple[str, str]:
        """用户名带毫秒时间戳，密码是用户名加 app_secret 的 MD5。"""
        username = (
            f"{self.app_key}|{self.si}|{self.client_type}|"
            f"{int(time.time() * 1000)}|{self.login_token}"
        )
        password = hashlib.md5((username + self.app_secret).encode()).hexdigest()
        return username, password

    @property
    def secret_key(self) -> bytes:
        return self.app_secret.encode()


def encode_frame(config: UiotConfig, json_str: str) -> bytes:
    """JSON -> AES-256-ECB -> zlib -> 78 字节头 + 体。"""
    ciphertext = AES.new(config.secret_key, AES.MODE_ECB).encrypt(
        pad(json_str.encode("utf-8"), AES.block_size)
    )
    header = bytearray(HEADER_LEN)
    header[0:4] = b"UIOT"
    header[5] = 0x01
    header[6 : 6 + len(config.app_key)] = config.app_key.encode()
    header[39] = 0x01
    header[40] = 0x01
    signature = hashlib.md5((json_str + config.app_secret).encode()).hexdigest()
    header[41:73] = signature.encode()
    header[74:77] = b"EOS"
    return bytes(header) + zlib.compress(ciphertext)


def decode_frame(config: UiotConfig, payload: bytes) -> dict[str, Any] | None:
    """UIOT 帧 -> JSON dict，非本协议或解不开时返回 None。"""
    if len(payload) < HEADER_LEN or payload[0:4] != b"UIOT":
        return None
    eos = payload.find(b"EOS", 70)
    body = payload[eos + 4 :] if eos > 0 else b""
    if not body or body[0] != 0x78:
        return None
    try:
        ciphertext = zlib.decompress(body)
        plaintext = unpad(
            AES.new(config.secret_key, AES.MODE_ECB).decrypt(ciphertext),
            AES.block_size,
        )
        return json.loads(plaintext.decode("utf-8"))
    except (ValueError, zlib.error):
        return None


def build_request(config: UiotConfig, msg_id: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "header": {
                "clientType": config.client_type,
                "identity": config.si,
                "msgId": msg_id,
                "appkey": config.app_key,
                "userUnique": config.user_unique,
                "params": {"si": config.si},
                "version": "1.0",
                "isEncrypt": "true",
            },
            "payload": payload,
        },
        separators=(",", ":"),
    )


def build_login_payload(config: UiotConfig) -> dict[str, Any]:
    return {
        "areaCode": "",
        "loginType": 1,
        "oem": "0X8601",
        "si": config.si,
        "userPwd": "",
        "qrCodePwd": "",
        "userUnique": config.user_unique,
        "sn": config.host_sn,
        "userName": "",
    }
