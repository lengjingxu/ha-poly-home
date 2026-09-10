# ha-poly-home

保利智家（UIOT 二次开发）局域网中控网关的 Home Assistant 自定义集成。
集成直接连接网关的 MQTT 1883 端口，认证、查询和控制都在本地完成，不经过保利云。

## 支持的实体

| 平台 | 设备 | 说明 |
| --- | --- | --- |
| `light` | 面板继电器 | 开关 |
| `climate` | 485 中央空调室内机 | 制冷/制热/送风、设定温度 16–30 ℃、风速、当前温度 |
| `fan` | 新风机组 | 开关与三档风速 |
| `binary_sensor` | 门窗磁 | 开/关 |
| `sensor` | 带电池的设备 | 电量 |

复合面板、场景按键、中控网关自身没有可控属性，不生成实体。

## 安装

HACS：HACS → 集成 → 右上角菜单 → 自定义存储库 → 填本仓库地址，类型选 Integration → 安装 → 重启 Home Assistant。

手动：把 `custom_components/poly_home` 整个目录复制到 HA 配置目录的 `custom_components/` 下，重启 Home Assistant。

## 配置

添加集成「保利智家本地网关」，填入以下字段：

| 字段 | 说明 |
| --- | --- |
| `gateway_host` | 网关局域网地址，形如 `192.168.1.2:1883` |
| `host_sn` | 网关序列号 |
| `si` | App 设备标识 |
| `login_token` | 云端签发的登录令牌 |
| `user_unique` | 用户标识 |
| `app_key` | App 级常量 |
| `app_secret` | App 级常量 |

前五项是用户级凭据，从保利智家 App 的 SharedPreferences 里读。手机或模拟器登录 App 后：

```bash
python3 scripts/extract_credentials.py            # 需要 adb 与 root，多设备时加 --serial
```

本仓库不包含云端的手机号验证码登录流程，凭据全部由上面的脚本从已登录的 App 本地读取，仓库里没有作者的账号数据。

`app_key` 与 `app_secret` 是 App 级常量，所有用户相同，来自 APK 逆向，取值过程见 `docs/PROTOCOL.md`。

## 工作原理

- 连接认证：`username = appKey|si|poly_app|毫秒时间戳|loginToken`，`password = MD5(username + appSecret)`。
- 业务载荷：JSON → AES-256-ECB → zlib → 78 字节固定头，MQTT 传输层本身是明文。
- 登录后订阅 `app/host/+/{si}/#` 与 `common/host/+/{host_sn}/#`，请求与响应按 `msgId` 配对。
- 状态每 30 秒查询一次；下发控制后先本地更新，2 秒后再查一次覆盖。
- MQTT 断线由 paho 自动重连，重连后自动补一次 `localLogin`。

完整协议说明见 `docs/PROTOCOL.md`。

## 已知限制

- `login_token` 由云端签发，过期后网关会拒绝登录；HA 会提示重新认证，重新提取填一次即可。
- 场景执行（`smartExecution`）的 payload 未经过抓包验证，集成没有实现。
- 网关协议没有 TLS，也没有逐请求鉴权，拿到凭据的人都能控制设备，只应在可信局域网里使用。

## 免责声明

本项目是非官方的逆向实现，与保利发展、UIOT 均无关联，仅供在自己的设备上使用，风险自负。

## License

MIT
