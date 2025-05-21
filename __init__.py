from plugins import register
from .main import MacMessageForwarder

@register(
    name="MacMessageForwarder",
    desire_priority=90,
    hidden=False,
    desc="Mac协议消息转发插件 - 支持转发所有类型消息，包括图片、表情包、语音、视频、文件、小程序等",
    version="1.0.0",
    author="Claude"
)
def get_plugin():
    return MacMessageForwarder() 
