import time
import hashlib
import json
import logging
from typing import Dict, List, Optional, Set, Any, Union
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import PluginBase, Event, EventContext, EventAction
from channel.bot import BOT
import asyncio

class MacMessageForwarder(PluginBase):
    """
    Mac协议消息转发插件 - 支持转发所有类型消息，包括
    1. 文本消息
    2. 图片消息
    3. 表情包
    4. 语音
    5. 视频
    6. 文件
    7. 小程序
    8. 聊天记录
    9. 链接卡片等
    """
    
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.dedup_cache: Dict[str, float] = {}  # 用于消息去重
        logger.info("[MacMessageForwarder] 插件已初始化")
        
        # 支持的消息类型
        self.supported_types = [
            ContextType.TEXT,           # 文本消息
            ContextType.IMAGE,          # 图片消息  
            ContextType.VOICE,          # 语音消息
            ContextType.VIDEO,          # 视频消息
            ContextType.FILE,           # 文件消息
            ContextType.SHARING,        # 分享消息(小程序/链接)
        ]
        
        # 创建事件循环，用于异步任务
        self.loop = asyncio.new_event_loop()
        
        # 错误重试配置
        self.max_retries = 3
        self.retry_delay = 1  # 秒
        
        # 保存所有待处理的原始消息，key为msg_id
        self.raw_messages = {}

    def get_help_text(self, **kwargs):
        help_text = "Mac协议消息转发插件使用说明：\n"
        help_text += "1. 配置监听源群：source_group\n"
        help_text += "2. 配置目标群：target_group\n"
        help_text += "3. 配置监听用户：monitor_users (可选，为空表示监听所有用户)\n"
        help_text += "4. 支持转发所有类型消息，包括图片、语音、视频、文件、聊天记录、小程序等\n"
        help_text += "5. 可配置是否显示原始发送者信息：show_sender_info\n"
        return help_text

    def on_handle_context(self, e_context: EventContext):
        """处理接收到的消息"""
        context = e_context['context']
        
        # 如果不是支持的消息类型，直接返回
        if context.type not in self.supported_types:
            return
            
        try:
            # 获取消息来源信息
            if hasattr(context, 'from_user_id'):
                from_user_id = context.from_user_id
            else:
                # 某些消息可能没有from_user_id，尝试其他可能的属性
                from_user_id = context.get('from_user_id', '')
                
            # 判断是否为群消息
            is_group_message = '@chatroom' in from_user_id if from_user_id else False
            
            # 如果不是群消息，直接返回
            if not is_group_message:
                return
                
            # 获取发送者信息
            sender_id = None
            sender_name = None
            
            if hasattr(context, 'actual_user_id'):
                sender_id = context.actual_user_id
            elif hasattr(context, 'sender_wxid'):
                sender_id = context.sender_wxid
                
            if hasattr(context, 'actual_user_nickname'):
                sender_name = context.actual_user_nickname
            
            # 检查是否需要转发
            if not self._should_forward(from_user_id, sender_id):
                return
                
            # 获取消息内容和类型
            msg_content = context.content
            msg_type = context.type
            
            # 记录原始消息，用于获取XML
            if hasattr(context, 'msg_id'):
                msg_id = context.msg_id
                self.raw_messages[msg_id] = context.raw
            
            # 执行消息转发
            self._forward_message(e_context, from_user_id, sender_id, sender_name)
            
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 处理消息时出错: {e}")

    def _should_forward(self, from_group_id: str, sender_id: str) -> bool:
        """判断是否需要转发消息"""
        # 获取配置
        config = self.get_config()
        source_group = config.get('source_group', '')
        monitor_users = config.get('monitor_users', [])
        
        # 检查来源群组是否匹配
        if not source_group:
            logger.warning("[MacMessageForwarder] 未配置来源群组")
            return False
            
        if source_group != from_group_id:
            return False
            
        # 检查发送者是否匹配(如果配置了monitor_users)
        if monitor_users and sender_id not in monitor_users:
            return False
            
        return True

    def _forward_message(self, e_context: EventContext, from_group_id: str, sender_id: str, sender_name: str):
        """转发消息到目标群"""
        # 获取配置
        config = self.get_config()
        target_group = config.get('target_group', '')
        show_sender_info = config.get('show_sender_info', True)
        
        if not target_group:
            logger.error("[MacMessageForwarder] 未配置目标群组")
            return
            
        # 消息去重
        context = e_context['context']
        msg_hash = self._get_message_hash(context, from_group_id)
        if self._is_duplicate(msg_hash):
            logger.info(f"[MacMessageForwarder] 检测到重复消息，已跳过转发")
            return
            
        # 根据消息类型转发
        msg_type = context.type
        
        try:
            # 启动异步任务处理转发
            asyncio.run_coroutine_threadsafe(
                self._forward_message_async(e_context, msg_type, target_group, sender_name if show_sender_info else None),
                self.loop
            )
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发消息时出错: {e}")

    async def _forward_message_async(self, e_context: EventContext, msg_type: ContextType, target_group: str, sender_name: Optional[str]):
        """异步转发消息"""
        context = e_context['context']
        
        # 根据消息类型调用不同的转发方法
        if msg_type == ContextType.TEXT:
            await self._forward_text(e_context, target_group, sender_name)
            
        elif msg_type == ContextType.IMAGE:
            await self._forward_image(e_context, target_group, sender_name)
            
        elif msg_type == ContextType.VOICE:
            await self._forward_voice(e_context, target_group, sender_name)
            
        elif msg_type == ContextType.VIDEO:
            await self._forward_video(e_context, target_group, sender_name)
            
        elif msg_type == ContextType.FILE:
            await self._forward_file(e_context, target_group, sender_name)
            
        elif msg_type == ContextType.SHARING:
            await self._forward_sharing(e_context, target_group, sender_name)
            
        else:
            logger.warning(f"[MacMessageForwarder] 不支持的消息类型: {msg_type}")

    async def _forward_text(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发文本消息"""
        try:
            content = e_context['context'].content
            
            # 如果需要显示发送者信息，添加到消息前面
            if sender_name:
                content = f"[{sender_name}]:\n{content}"
                
            reply = Reply(ReplyType.TEXT, content)
            e_context['channel'].send(reply, target_group)
            logger.info(f"[MacMessageForwarder] 文本消息已转发到 {target_group}")
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发文本消息失败: {e}")

    async def _forward_image(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发图片消息"""
        try:
            context = e_context['context']
            raw_message = None
            
            # 获取原始消息对象
            if hasattr(context, 'msg_id') and context.msg_id in self.raw_messages:
                raw_message = self.raw_messages[context.msg_id]
                
            # 优先使用原始消息中的XML进行转发
            if raw_message and hasattr(raw_message, 'xml'):
                # 使用Mac协议的CDN图片转发功能
                bot = BOT().bot
                if hasattr(bot, 'send_cdn_img_msg'):
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            await bot.send_cdn_img_msg(target_group, xml)
                            logger.info(f"[MacMessageForwarder] 图片消息已通过XML转发到 {target_group}")
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 图片来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            return
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发图片失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
            
            # 回退到普通方式：通过URL或路径发送
            image_url = context.content
            reply = Reply(ReplyType.IMAGE_URL, image_url)
            e_context['channel'].send(reply, target_group)
            logger.info(f"[MacMessageForwarder] 图片消息已通过URL转发到 {target_group}")
            
            # 如果需要显示发送者信息，额外发送一条文本消息
            if sender_name:
                sender_text = f"👆 图片来自: {sender_name}"
                reply = Reply(ReplyType.TEXT, sender_text)
                e_context['channel'].send(reply, target_group)
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发图片消息失败: {e}")

    async def _forward_voice(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发语音消息"""
        try:
            context = e_context['context']
            raw_message = None
            
            # 获取原始消息对象
            if hasattr(context, 'msg_id') and context.msg_id in self.raw_messages:
                raw_message = self.raw_messages[context.msg_id]
                
            # 优先使用原始消息中的XML进行转发
            if raw_message and hasattr(raw_message, 'xml'):
                # 使用Mac协议的语音转发功能
                bot = BOT().bot
                if hasattr(bot, 'send_cdn_voice_msg'):
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            await bot.send_cdn_voice_msg(target_group, xml)
                            logger.info(f"[MacMessageForwarder] 语音消息已通过XML转发到 {target_group}")
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 语音来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            return
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发语音失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
                
            # 回退处理：将语音转发为文本提示
            if sender_name:
                sender_text = f"[{sender_name}] 发送了一条语音消息，但无法直接转发"
            else:
                sender_text = "收到一条语音消息，但无法直接转发"
            
            reply = Reply(ReplyType.TEXT, sender_text)
            e_context['channel'].send(reply, target_group)
            logger.info(f"[MacMessageForwarder] 语音消息无法直接转发，已发送提示到 {target_group}")
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发语音消息失败: {e}")

    async def _forward_video(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发视频消息"""
        try:
            context = e_context['context']
            raw_message = None
            
            # 获取原始消息对象
            if hasattr(context, 'msg_id') and context.msg_id in self.raw_messages:
                raw_message = self.raw_messages[context.msg_id]
                
            # 优先使用原始消息中的XML进行转发
            if raw_message and hasattr(raw_message, 'xml'):
                # 使用Mac协议的视频转发功能
                bot = BOT().bot
                if hasattr(bot, 'send_cdn_video_msg'):
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            await bot.send_cdn_video_msg(target_group, xml)
                            logger.info(f"[MacMessageForwarder] 视频消息已通过XML转发到 {target_group}")
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 视频来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            return
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发视频失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
            
            # 回退处理：发送视频文件或提示
            video_url = context.content
            if video_url and (video_url.startswith('http') or video_url.startswith('/')):
                # 尝试作为普通消息发送
                reply = Reply(ReplyType.TEXT, f"收到视频消息，链接为: {video_url}")
                e_context['channel'].send(reply, target_group)
                
                if sender_name:
                    sender_text = f"👆 视频来自: {sender_name}"
                    reply = Reply(ReplyType.TEXT, sender_text)
                    e_context['channel'].send(reply, target_group)
            else:
                # 无法处理，发送提示
                if sender_name:
                    sender_text = f"[{sender_name}] 发送了一条视频消息，但无法直接转发"
                else:
                    sender_text = "收到一条视频消息，但无法直接转发"
                
                reply = Reply(ReplyType.TEXT, sender_text)
                e_context['channel'].send(reply, target_group)
                
            logger.info(f"[MacMessageForwarder] 视频消息已尝试转发到 {target_group}")
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发视频消息失败: {e}")

    async def _forward_file(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发文件消息"""
        try:
            context = e_context['context']
            raw_message = None
            
            # 获取原始消息对象
            if hasattr(context, 'msg_id') and context.msg_id in self.raw_messages:
                raw_message = self.raw_messages[context.msg_id]
                
            # 优先使用原始消息中的XML进行转发
            if raw_message and hasattr(raw_message, 'xml'):
                # 使用Mac协议的文件转发功能
                bot = BOT().bot
                if hasattr(bot, 'send_cdn_file_msg'):
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            await bot.send_cdn_file_msg(target_group, xml)
                            logger.info(f"[MacMessageForwarder] 文件消息已通过XML转发到 {target_group}")
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 文件来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            return
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发文件失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
            
            # 回退处理：尝试获取文件名
            file_path = context.content
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path.split('\\')[-1] if '\\' in file_path else "未知文件"
            
            # 发送文件信息提示
            if sender_name:
                reply_text = f"[{sender_name}] 发送了文件: {file_name}，但无法直接转发"
            else:
                reply_text = f"收到文件: {file_name}，但无法直接转发"
                
            reply = Reply(ReplyType.TEXT, reply_text)
            e_context['channel'].send(reply, target_group)
            logger.info(f"[MacMessageForwarder] 文件消息无法直接转发，已发送提示到 {target_group}")
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发文件消息失败: {e}")

    async def _forward_sharing(self, e_context: EventContext, target_group: str, sender_name: Optional[str]):
        """转发分享消息(小程序/链接)"""
        try:
            context = e_context['context']
            raw_message = None
            sharing_content = context.content
            
            # 获取原始消息对象
            if hasattr(context, 'msg_id') and context.msg_id in self.raw_messages:
                raw_message = self.raw_messages[context.msg_id]
                
            # 判断是否为小程序消息
            is_mini_program = False
            if isinstance(sharing_content, str) and "gh_" in sharing_content:
                is_mini_program = True
            elif isinstance(sharing_content, dict) and "appid" in sharing_content:
                is_mini_program = True
                
            # 优先使用原始消息中的XML进行转发
            if raw_message and hasattr(raw_message, 'xml'):
                # 使用Mac协议的转发功能
                bot = BOT().bot
                try_forward = False
                
                if is_mini_program and hasattr(bot, 'forward_mini_app'):
                    # 小程序转发
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            # 获取小程序封面URL
                            cover_img_url = ""
                            if isinstance(sharing_content, dict) and "thumb_url" in sharing_content:
                                cover_img_url = sharing_content["thumb_url"]
                                
                            await bot.forward_mini_app(target_group, xml, cover_img_url)
                            logger.info(f"[MacMessageForwarder] 小程序消息已通过XML转发到 {target_group}")
                            try_forward = True
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 小程序来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            break
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发小程序失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
                
                elif hasattr(bot, 'forward_url'):
                    # 链接转发
                    xml = raw_message.xml
                    for i in range(self.max_retries):
                        try:
                            await bot.forward_url(target_group, xml)
                            logger.info(f"[MacMessageForwarder] 链接消息已通过XML转发到 {target_group}")
                            try_forward = True
                            
                            # 如果需要显示发送者信息，额外发送一条文本消息
                            if sender_name:
                                sender_text = f"👆 链接来自: {sender_name}"
                                reply = Reply(ReplyType.TEXT, sender_text)
                                e_context['channel'].send(reply, target_group)
                                
                            break
                        except Exception as e:
                            logger.warning(f"[MacMessageForwarder] 通过XML转发链接失败(尝试 {i+1}/{self.max_retries}): {e}")
                            await asyncio.sleep(self.retry_delay)
                
                # 如果已成功转发，直接返回
                if try_forward:
                    return
            
            # 回退处理：尝试作为分享消息转发
            try:
                # 解析分享内容
                if isinstance(sharing_content, str):
                    try:
                        sharing_content = json.loads(sharing_content)
                    except:
                        # 可能是URL字符串
                        sharing_content = {"url": sharing_content}
                
                # 获取分享信息
                if isinstance(sharing_content, dict):
                    title = sharing_content.get('title', '未知标题')
                    description = sharing_content.get('description', '')
                    url = sharing_content.get('url', '')
                    thumb_url = sharing_content.get('thumb_url', '')
                    
                    # 作为分享消息转发
                    reply = Reply(ReplyType.SHARING, {
                        'title': title,
                        'description': description,
                        'url': url,
                        'thumb_url': thumb_url
                    })
                    e_context['channel'].send(reply, target_group)
                    logger.info(f"[MacMessageForwarder] 分享消息已转发到 {target_group}")
                    
                    # 如果需要显示发送者信息，额外发送一条文本消息
                    if sender_name:
                        sender_text = f"👆 分享来自: {sender_name}"
                        reply = Reply(ReplyType.TEXT, sender_text)
                        e_context['channel'].send(reply, target_group)
                else:
                    # 无法解析，发送原始内容
                    if sender_name:
                        reply_text = f"[{sender_name}] 发送了一条分享消息: {sharing_content}"
                    else:
                        reply_text = f"收到分享消息: {sharing_content}"
                        
                    reply = Reply(ReplyType.TEXT, reply_text)
                    e_context['channel'].send(reply, target_group)
                    logger.info(f"[MacMessageForwarder] 无法解析的分享消息，已发送提示到 {target_group}")
            except Exception as e:
                logger.error(f"[MacMessageForwarder] 解析分享内容失败: {e}")
                
                # 发送错误提示
                if sender_name:
                    reply_text = f"[{sender_name}] 发送了一条无法转发的分享消息"
                else:
                    reply_text = "收到一条无法转发的分享消息"
                    
                reply = Reply(ReplyType.TEXT, reply_text)
                e_context['channel'].send(reply, target_group)
        except Exception as e:
            logger.error(f"[MacMessageForwarder] 转发分享消息失败: {e}")

    def _get_message_hash(self, context, from_group_id: str) -> str:
        """生成消息的唯一哈希值用于去重"""
        msg_id = getattr(context, 'msg_id', '')
        if msg_id:
            # 有消息ID，直接使用
            return f"{from_group_id}:{msg_id}"
            
        # 没有消息ID，使用内容+时间戳生成哈希
        content = str(context.content)[:100]  # 取前100个字符，避免过长
        msg_type = str(context.type)
        create_time = str(int(time.time() * 1000))
        
        # 组合消息特征
        msg_str = f"{msg_type}:{from_group_id}:{content}:{create_time}"
        return hashlib.md5(msg_str.encode()).hexdigest()

    def _is_duplicate(self, msg_hash: str) -> bool:
        """检查消息是否重复"""
        now = time.time()
        if msg_hash in self.dedup_cache:
            # 如果消息在1分钟内重复，返回True
            if now - self.dedup_cache[msg_hash] < 60:
                return True
        self.dedup_cache[msg_hash] = now
        
        # 清理过期的缓存项(超过10分钟的)
        expired_keys = [k for k, v in self.dedup_cache.items() if now - v > 600]
        for k in expired_keys:
            del self.dedup_cache[k]
            
        return False

    def get_config(self) -> dict:
        """获取插件配置"""
        config = super().get_config()
        if not config:
            # 默认配置
            config = {
                "source_group": "",  # 要监听的群ID，必须填写
                "target_group": "",  # 消息要转发到的目标群ID，必须填写
                "monitor_users": [],  # 要监听的用户ID列表，为空则监听所有用户
                "show_sender_info": True,  # 是否在转发的消息中显示原发送者信息
                "max_retries": 3,  # 转发失败时的最大重试次数
                "retry_delay": 1,  # 重试间隔(秒)
            }
        return config 
