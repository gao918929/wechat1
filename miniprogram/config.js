// 后端地址：开发者工具中可用 127.0.0.1；真机调试请改为电脑的局域网 IP（并在开发者工具中勾选“不校验合法域名”）。
// 正式发布需配置 HTTPS / WSS 合法域名。
module.exports = {
  baseUrl: 'http://127.0.0.1:8000',
  wsUrl: 'ws://127.0.0.1:8000',
  // 订阅消息模板 ID（“计划生成完成”通知，可选；需与后端 WECHAT_PLAN_TEMPLATE_ID 一致）
  planTemplateId: ''
};
