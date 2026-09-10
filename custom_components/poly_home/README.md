# 保利智家本地网关（Home Assistant 自定义集成）

直连局域网里的保利智家中控网关（UIOT 二次开发，MQTT 1883），不经过保利云。
协议细节见仓库 `docs/PROTOCOL.md`。

## 实体

| 平台 | 来源 | 说明 |
| --- | --- | --- |
| `light` | `deviceType=intelligentLighting` 且有 `powerSwitch` | 面板继电器控制的灯具 |
| `climate` | `deviceType=intelligentHvac` 且有 `targetTemperature` | 485 中央空调室内机，支持模式、设定温度、风速、当前温度 |
| `fan` | `deviceType=intelligentHvac` 且有 `windSpeed` 无 `targetTemperature` | 新风机组，三档风速 |
| `binary_sensor` | `deviceType=intelligentSafeguard` 且有 `contactState` | 门窗磁，`open` 为 on |
| `sensor` | 有 `batteryPercentage` 的设备 | 电池电量 |

复合面板、场景按键、网关自身只有配置属性，不生成实体。

## 配置字段

添加集成时用手机号 + 短信验证码登录，家庭和网关地址自动带出；也可以手动填写下表。

| 字段 | 来源 |
| --- | --- |
| `gateway_host` | 网关局域网地址，形如 `192.168.1.2:1883` |
| `host_sn` | 网关序列号 |
| `si` | 云端 `backdevice.si.register` 签发的设备标识 |
| `login_token` | 云端 `app.login.verifyCode` 返回的登录令牌 |
| `user_unique` | 用户标识 |
| `app_key` | App 级常量 |
| `app_secret` | App 级常量，从 APK 逆向所得 |

## 行为

- 状态每 30 秒查询一次网关；下发控制后先本地更新，2 秒后再查一次覆盖。
- MQTT 断线由 paho 自动重连，重连后自动补一次 `localLogin`。
- 网关不校验 `login_token`，凭据配好后不会过期；网关只放行云端注册过的 `si`。
- 所有阻塞调用都走 executor 线程，不占用事件循环。

## 注意

- 网关无 TLS、无逐请求鉴权，任何拿到凭据的人都能控制设备；凭据只保存在 HA 配置目录中。
- 客户端 id 是 `poly_home_{si}`，配置校验用 `poly_home_{si}_probe`，不会互相踢下线。
