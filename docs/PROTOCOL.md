# 保利智家本地网关操作实现说明

本文说明如何不依赖官方 App / 云服务，直接在局域网对保利智家中控网关
（UIOT 二次开发，MQTT 1883 端口）完成认证、查询、控制。
所有结论均经真实抓包 + 在线请求验证（2026-08-12，APK V5.02.010，360 加固）。

> 配套代码：`custom_components/poly_home/protocol.py`（编解码）、`gateway.py`（网关客户端）、`coordinator.py`（轮询与下发）。

---

## 1. 总体链路

```
Home Assistant ──MQTT 1883──> 中控网关(192.168.1.x)
        └── UIOT 封包: JSON→AES-256-ECB→zlib→78B 头
```

- 传输层是**明文 MQTT v3.1.1**（无 TLS），但每条业务消息的 payload 是加密的。
- 网关只认「MQTT 连接认证 + localLogin」两步，之后才响应查询/控制。

## 2. 需要的凭据

| 凭据 | 值 / 来源 | 性质 |
|------|----------|------|
| `app_key` | `0e71bdeec1089eff` | App 级常量（APK 字符串，所有用户相同） |
| `app_secret` | `a327414670fffdea655ec4b988988ec7` | App 级常量，native `libuiot_screen_click.so` 运行时解密；取法：root 设备 Frida 执行 `Java.use('cc.a').a()` |
| `oem` | `0X8601` | App 级常量 |
| `login_token` | App 登录后写入 SharedPreferences `login_token`（32 位 hex） | 用户级，会过期，过期需在 App 重新登录后重取 |
| `host_sn` | SharedPreferences `host_sn`（网关序列号） | 用户级 |
| `si` | SharedPreferences `APP_SI`（App 设备标识） | 用户级 |
| `user_unique` | SharedPreferences `uniqkey` | 用户级 |

提取脚本：`scripts/extract_credentials.py`（adb root 读取 SharedPreferences，输出 `config.json`）。

## 3. MQTT 连接认证

```
clientId : 任意（App 用 poly_app-{si}-{毫秒}）
username : {app_key}|{si}|poly_app|{毫秒时间戳}|{login_token}
password : md5(username + app_secret)   # 小写 hex
```

已用 3 组 App 抓包样本复算验证，全部命中。CONNACK rc=0 即连接成功。

## 4. UIOT 消息封包（核心）

业务 JSON 先加密压缩，再套 78 字节固定头：

```
plaintext = JSON envelope（见 §6）
ciphertext = AES-256-ECB(key=app_secret 原文 32 字节, PKCS7).encrypt(plaintext)
compressed = zlib.compress(ciphertext)

frame = header(78B) + compressed
```

78 字节头布局（offset 均为十进制）：

| offset | 长度 | 内容 |
|--------|------|------|
| 0 | 4 | `UIOT` |
| 4 | 1 | `0x00` |
| 5 | 1 | `0x01` |
| 6 | 16 | `app_key` ASCII |
| 22 | 17 | `0x00` 填充 |
| 39 | 1 | `0x01` |
| 40 | 1 | `0x01` |
| 41 | 32 | `md5(json + app_secret)` ASCII（签名） |
| 73 | 1 | `0x00` |
| 74 | 3 | `EOS` |
| 77 | 1 | `0x00` |
| 78+ | n | zlib 流 |

**解码**：定位 `EOS`，取 `payload[eos+4:]` 为 zlib 流 → 解压 → AES-ECB 解密 → 去 PKCS7 → JSON。
（对应 APK smali `pb/a.smali` = MqttCryptoUtil、`utils/r.smali` = Md5。）

## 5. Topic 结构

请求（App→网关）：`host/app/{section}/{host_sn}/{method}`
响应（网关→App）：`app/host/{section}/{si}/{method}`，按 header.msgId 与请求配对。

| method | section | 用途 |
|--------|---------|------|
| `localLogin` | localLogin | 局域网登录（必须先做） |
| `getDeviceList` | deviceInfo | 设备清单（名称/型号/房间） |
| `getDeviceStateList` | deviceInfo | 设备实时状态 properties |
| `deviceControl` | deviceControl | 下发控制 |
| `getSmartState` | smartScene | 场景列表（只读） |

状态推送订阅：`common/host/+/{host_sn}/#`
（`common/host/deviceState/{sn}/deviceStateReport` 为设备状态变化上报）。

**注意**：msgId 必须全局唯一（并发请求同毫秒会串响应），实现用 `time_ns + uuid`。

## 6. JSON envelope 与关键 payload

请求 envelope：

```json
{"header":{"clientType":"poly_app","identity":"{si}","msgId":"<唯一>",
  "appkey":"0e71bdeec1089eff","userUnique":"{user_unique}",
  "params":{"si":"{si}"},"version":"1.0","isEncrypt":"true"},
 "payload":{...}}
```

### localLogin（缺字段返回 280105）

```json
{"areaCode":"","loginType":1,"oem":"0X8601","si":"{si}",
 "userPwd":"","qrCodePwd":"","userUnique":"{user_unique}",
 "sn":"{host_sn}","userName":""}
```

成功返回 `code=0`，data 含 `homeName/homeId/userType`。

### deviceControl

```json
{"controlSources":"user","sn":"{host_sn}","deviceId":9,
 "properties":{"powerSwitch":"on"},
 "controlSourcesIdentity":{"triggerType":2,"userUnique":"{user_unique}","userType":1}}
```

### 常用 properties

| 设备 | 可控键 | 说明 |
|------|--------|------|
| 灯/开关 | `powerSwitch` | `"on"` / `"off"` |
| 空调/新风 | `powerSwitch`、`targetTemperature`(字符串)、`thermostatMode`(`cool/heat/fan/innerLoop`)、`windSpeed`(`low/medium/high/auto`) | |
| 门窗磁 | 只读 | `contactState`、`batteryPercentage` |

响应 envelope：`{"code":0,"desc":"","data":{...}}`；`code!=0` 即失败
（`280301` 未登录主机，`280105` 缺约定字段）。

## 7. 对应到集成代码

```python
# custom_components/poly_home/protocol.py
cfg = UiotConfig(entry_data)                 # app_key / app_secret / si / login_token / ...
frame = encode_frame(cfg, build_request(cfg, msg_id, build_login_payload(cfg)))

# custom_components/poly_home/gateway.py
gw = GatewayClient(cfg)
gw.connect()                                 # MQTT CONNECT + localLogin
devices = gw.get_devices()                   # getDeviceStateList，按 deviceId 索引
gw.control_device(9, {"powerSwitch": "on"})  # 开客厅灯带
```

## 8. 逆向路径备忘（如何得到以上结论）

1. APK 360 加固 → `frida-dexdump` 内存 dump 64 个 DEX → `baksmali` 反汇编。
2. `MqttClientManager.smali`：username/password 生成（`utils/r.c` = MD5）。
3. `pb/a.smali`（MqttCryptoUtil）：78B 头 + AES/zlib 顺序。
4. `cc/a.smali` + Frida 直调 `cc.a.a()`：app_secret。
5. 模拟器 tcpdump（root）+ 本地 TCP 重组：解出 App 全部请求/响应 JSON，
   确认 localLogin 必需字段与 deviceControl payload。
6. 在线验证：Mac 直连网关，localLogin→getDeviceList→deviceControl 全链路 code=0，状态回读一致。

## 9. 边界与风险

- `login_token` 由云端签发，过期后必须用 App 重新登录刷新；账号密码直登接口未验证。
- 场景执行（`smartExecution`）payload 未抓包验证，当前只读不开放。
- 网关无 TLS、无每请求鉴权，局域网内任何拿到凭据者均可控制——服务务必只绑 127.0.0.1。

## 10. 云端登录 bootstrap（手机号+验证码）实测边界

目标：页面输手机号+验证码即可完成 bootstrap，无需从 App 提取凭据。
脚本 `cloud_login.py`（同进程全链 + cookie jar 每步持久化）。

**已验证（2026-08-12 实测）**
- Web 登录流程（登录页 JS 逆向）：`sendMsg`(JSON) → `checkCode`(JSON,会话级)
  → `getUserSnNew`(form) → `login.do`(form 复合 username) → 302 授权码 → `token`。
- `sendMsg` 真实下发验证码（`code:0`）；`checkCode` 校验通过（`code:0`）。
- 密码直登不通：`getUserSnNew` 带密码返回 `130104 用户名密码错误`。

**未验证（候选方向，不得当作已通）**
- `checkCode` 成功后 `getUserSnNew` 尚未在同会话实测返回 `snList`
  （snList 结构仅来自 Web JS 读取）→ host_sn 云端发现**未验证**。
- `PPAQ…/u4rm…` 来自 APK 京东第三方绑定流程（`tpp.oauth.saveJdToken`），
  仅作 token 交换候选之一，**不是已验证的主登录 OAuth 凭据**。
- `access_token` 能否当 MQTT `login_token` 未验证；`userUnique` 来源未验证。
- `si`：App 用 AndroidId/自生成标识，服务端自生成+持久化为候选方案。
- 网关 LAN IP：App 用 mDNS `_smart._tcp`（NsdHelper.kt）；不在同网时手动 IP 兜底。

**结论**：账号+验证码输入本身尚不能完成控制 bootstrap；
必须同会话实测到 `login.do` 原始跳转并确认 token 链后，才集成页面登录。
