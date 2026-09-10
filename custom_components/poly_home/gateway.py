"""保利智家网关 MQTT 客户端。

一条长连接：CONNECT 认证 -> localLogin -> 订阅响应主题，请求按 msgId 配对。
方法都是阻塞调用，调用方放在 executor 线程里执行。重连后自动补一次 localLogin。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt

from .const import AUTH_ERROR_CODE, LOGIN_LIMIT_ERROR_CODE
from .protocol import (
    UiotConfig,
    build_login_payload,
    build_request,
    decode_frame,
    encode_frame,
)

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 8.0
CONNACK_TIMEOUT = 8.0


class GatewayUnreachable(Exception):
    """网关连不上或没有响应。"""


class GatewayAuthFailed(Exception):
    """凭据被网关拒绝。"""


class GatewayLoginLimit(GatewayAuthFailed):
    """账号的局域网登录设备数已达上限。"""


class GatewayClient:
    def __init__(self, config: UiotConfig, client_suffix: str = '') -> None:
        self.client_id = 'poly_home_' + config.si + client_suffix
        self.cfg = config
        self.connected = False
        self.logged_in = False
        self.home_name = ""
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._connack = threading.Event()
        self._connack_seen = False
        self._client: mqtt.Client | None = None

    # ---------- 连接生命周期 ----------
    def connect(self) -> str:
        """建立连接并登录，返回家庭名称。"""
        username, password = self.cfg.mqtt_credentials()
        client = mqtt.Client(
            client_id=self.client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.username_pw_set(username, password)
        self._client = client
        try:
            client.connect(self.cfg.host, self.cfg.port, keepalive=60)
        except OSError as err:
            self._client = None
            raise GatewayUnreachable(
                f"连接 {self.cfg.gateway_host} 失败: {err}"
            ) from err
        client.loop_start()
        try:
            if not self._connack.wait(CONNACK_TIMEOUT):
                raise GatewayUnreachable("网关未返回 CONNACK")
            if not self.connected:
                raise GatewayAuthFailed("MQTT 认证被拒")
            return self.local_login()
        except Exception:
            self.disconnect()
            raise

    def local_login(self) -> str:
        resp = self._call("localLogin", build_login_payload(self.cfg), "localLogin")
        if resp is None:
            self.logged_in = False
            raise GatewayUnreachable("localLogin 无响应")
        if resp.get("code") == LOGIN_LIMIT_ERROR_CODE:
            self.logged_in = False
            raise GatewayLoginLimit(f"localLogin 被拒: desc={resp.get('desc')}")
        if resp.get("code") != 0:
            self.logged_in = False
            raise GatewayAuthFailed(
                f"localLogin 被拒: code={resp.get('code')} desc={resp.get('desc')}"
            )
        self.home_name = (resp.get("data") or {}).get("homeName") or ""
        self.logged_in = True
        _LOGGER.debug("localLogin 成功: %s", self.home_name)
        return self.home_name

    def disconnect(self) -> None:
        self.connected = False
        self.logged_in = False
        client, self._client = self._client, None
        if client is not None:
            client.disconnect()
            client.loop_stop()

    def _relogin(self) -> None:
        try:
            self.local_login()
            _LOGGER.info("网关重连后已重新登录")
        except (GatewayUnreachable, GatewayAuthFailed) as err:
            _LOGGER.warning("网关重连后重新登录失败: %s", err)

    # ---------- MQTT 回调 ----------
    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        self.connected = rc == 0
        if self.connected:
            client.subscribe(f"app/host/+/{self.cfg.si}/#")
            client.subscribe(f"common/host/+/{self.cfg.host_sn}/#")
        reconnect = self._connack_seen
        self._connack_seen = True
        self._connack.set()
        if reconnect and self.connected:
            threading.Thread(target=self._relogin, daemon=True).start()

    def _on_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        self.connected = False
        self.logged_in = False
        _LOGGER.warning("网关 MQTT 断开 rc=%s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        frame = decode_frame(self.cfg, msg.payload)
        if not frame:
            return
        header = frame.get("header") or {}
        if header.get("clientType") != "host":
            return
        with self._lock:
            event = self._pending.get(header.get("msgId", ""))
            if event is not None:
                self._results[header["msgId"]] = frame.get("payload") or {}
        if event is not None:
            event.set()

    # ---------- 请求 ----------
    def _call(
        self, method: str, payload: dict[str, Any], section: str
    ) -> dict[str, Any] | None:
        if not self.connected or self._client is None:
            raise GatewayUnreachable("网关未连接")
        msg_id = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
        frame = encode_frame(self.cfg, build_request(self.cfg, msg_id, payload))
        event = threading.Event()
        with self._lock:
            self._pending[msg_id] = event
        self._client.publish(f"host/app/{section}/{self.cfg.host_sn}/{method}", frame)
        if not event.wait(RESPONSE_TIMEOUT):
            with self._lock:
                self._pending.pop(msg_id, None)
            raise GatewayUnreachable(f"{method} 超时无响应")
        with self._lock:
            self._pending.pop(msg_id, None)
            return self._results.pop(msg_id, None)

    @staticmethod
    def _checked(resp: dict[str, Any] | None) -> dict[str, Any]:
        if resp is None:
            raise GatewayUnreachable("网关无响应")
        code = resp.get("code")
        if code == AUTH_ERROR_CODE:
            raise GatewayAuthFailed(f"网关会话失效: code={code}")
        if code != 0:
            raise GatewayUnreachable(f"网关返回失败: code={code} desc={resp.get('desc')}")
        return resp.get("data") or {}

    # ---------- 业务接口 ----------
    def get_devices(self) -> dict[int, dict[str, Any]]:
        """设备清单与实时状态，按 deviceId 索引。"""
        data = self._checked(
            self._call("getDeviceStateList", {"sn": self.cfg.host_sn}, "deviceInfo")
        )
        return {d["deviceId"]: d for d in data.get("deviceList") or []}

    def control_device(self, device_id: int, properties: dict[str, Any]) -> None:
        self._checked(
            self._call(
                "deviceControl",
                {
                    "controlSources": "user",
                    "sn": self.cfg.host_sn,
                    "deviceId": device_id,
                    "properties": properties,
                    "controlSourcesIdentity": {
                        "triggerType": 2,
                        "userUnique": self.cfg.user_unique,
                        "userType": 1,
                    },
                },
                "deviceControl",
            )
        )
