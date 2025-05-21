# MacMessageForwarder 插件

这是一个针对Mac协议版本优化的消息转发插件，支持转发所有类型的消息，包括文本、图片、表情包、语音、视频、文件和小程序等。

## 功能特点

1. 支持监听特定群聊中指定用户的消息
2. 支持转发各类消息类型：
   - 文本消息
   - 图片消息
   - 表情包
   - 语音消息
   - 视频消息
   - 文件消息
   - 小程序/链接
   - 聊天记录
   
3. 高级功能：
   - 消息去重防止重复转发
   - 转发失败自动重试
   - 显示原始发送者信息
   - 适配Mac协议转发接口，提高成功率

## 配置说明

编辑 `plugins/MacMessageForwarder/config.json` 文件：

```json
{
    "source_group": "12345678@chatroom",  // 要监听的群ID，必须替换为实际的群ID
    "target_group": "87654321@chatroom",  // 消息要转发到的目标群ID，必须替换为实际的群ID
    "monitor_users": [],                  // 要监听的用户ID列表，为空则监听所有用户
    "show_sender_info": true,             // 是否在转发的消息中显示原发送者信息
    "max_retries": 3,                     // 转发失败时的最大重试次数
    "retry_delay": 1                      // 重试间隔(秒)
}
```

### 配置项说明

1. `source_group`: 要监听的源群ID，必须填写
2. `target_group`: 转发目标群ID，必须填写
3. `monitor_users`: 要监听的用户ID列表，为空表示监听群里所有人的消息
4. `show_sender_info`: 是否在转发的消息中显示原发送者信息
5. `max_retries`: 转发失败时的最大重试次数
6. `retry_delay`: 重试间隔(秒)

## 获取群ID和用户ID

1. 打开管理后台
2. 查看接收到的消息日志，可以找到群ID和用户ID
3. 群ID通常格式为 `xxxxxxxxxx@chatroom`
4. 用户ID通常格式为 `wxid_xxxxxxxxxx`

## 安装方法

1. 将 `MacMessageForwarder` 文件夹放入 `plugins` 目录
2. 确保目录结构如下：
   ```
   plugins/
     └── MacMessageForwarder/
         ├── main.py
         ├── config.json
         └── README.md
   ```
3. 重启机器人

## 常见问题

### Q: 为什么有些消息无法转发？

A: 可能原因：
- 大尺寸图片/视频：微信对媒体大小有限制，通常是20MB以内
- 原始消息XML无法获取：部分复杂消息可能无法获取原始XML数据
- 协议限制：Mac协议对某些特殊消息类型支持有限
- 权限问题：确保机器人在目标群有足够权限

### Q: 如何排查转发失败问题？

A: 
1. 检查日志：查看插件输出的日志信息
2. 减小文件大小：对于大文件，尝试压缩后再发送
3. 设置重试：增大配置中的`max_retries`值
4. 更新协议：确保使用最新版本的Mac协议

### Q: 如何监控特定人的消息？

A: 在配置中的`monitor_users`数组中添加该用户的wxid：
```json
"monitor_users": ["wxid_xxxxxxxxxx", "wxid_yyyyyyyyy"]
``` 
