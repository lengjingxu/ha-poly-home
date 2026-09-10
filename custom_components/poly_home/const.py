"""保利智家本地网关集成的常量。"""

from homeassistant.const import Platform

DOMAIN = "poly_home"

PLATFORMS = [
    Platform.LIGHT,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

CONF_GATEWAY_HOST = "gateway_host"
CONF_APP_KEY = "app_key"
CONF_APP_SECRET = "app_secret"
CONF_HOST_SN = "host_sn"
CONF_SI = "si"
CONF_LOGIN_TOKEN = "login_token"
CONF_USER_UNIQUE = "user_unique"
CONF_CLIENT_TYPE = "client_type"

DEFAULT_APP_KEY = "0e71bdeec1089eff"
DEFAULT_CLIENT_TYPE = "poly_app"
DEFAULT_GATEWAY_HOST = "192.168.1.2:1883"

POLL_INTERVAL_SECONDS = 30

DEVICE_TYPE_LIGHT = "intelligentLighting"
DEVICE_TYPE_HVAC = "intelligentHvac"
DEVICE_TYPE_SAFEGUARD = "intelligentSafeguard"

# 网关返回「未登录主机」时说明会话失效，需要重新认证
AUTH_ERROR_CODE = 280301
