# plugins/MessageForwarder/main.py
from utils.plugin_base import PluginBase
from WechatAPI import WechatAPIClient
from utils.decorators import *
import tomlkit

class MessageForwarder(PluginBase):
    description = "智能群消息转发器"
    author = "AI Assistant"
    version = "1.0.0"
    
    def __init__(self):
        super().__init__()
        self.load_config()
        self.rules = self.parse_rules()
        self.processed_msgs = set()  # 消息去重

    def parse_rules(self):
        """解析转发规则配置"""
        rules = []
        for rule in self.config.get("rules", []):
            rules.append({
                "name": rule.get("name", "未命名规则"),
                "source_groups": rule.get("source_groups", []),
                "target_groups": rule.get("target_groups", []),
                "keywords": rule.get("keywords", []),
                "exclude_users": rule.get("exclude_users", []),
                "forward_original": rule.get("forward_original", True),
                "add_prefix": rule.get("add_prefix", "")
            })
        return rules

    @on_text_message(priority=5)
    async def handle_message(self, bot: WechatAPIClient, message: dict):
        if message['IsGroup'] and not message['IsSelf']:
            msg_id = message['MsgId']
            if msg_id in self.processed_msgs:
                return
                
            content = message['Content']
            from_user = message['ActualNickName']
            room_id = message['FromUserName']

            for rule in self.rules:
                if self.match_rule(room_id, content, from_user, rule):
                    await self.forward_message(bot, content, rule)
                    self.processed_msgs.add(msg_id)
                    break  # 匹配一个规则后停止

    def match_rule(self, room_id, content, from_user, rule):
        """检查消息是否符合转发规则"""
        # 群组匹配检查
        if room_id not in rule["source_groups"]:
            return False
        
        # 用户黑名单检查
        if from_user in rule["exclude_users"]:
            return False
        
        # 关键词匹配检查
        if rule["keywords"]:
            return any(keyword in content for keyword in rule["keywords"])
        return True

    async def forward_message(self, bot, content, rule):
        """执行消息转发"""
        for target in rule["target_groups"]:
            try:
                final_content = f"{rule['add_prefix']}{content}"
                await bot.send_text(target, final_content)
            except Exception as e:
                self.logger.error(f"转发到群{target}失败: {str(e)}")
