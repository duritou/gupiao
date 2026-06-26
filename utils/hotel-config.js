// 酒店模块配置 — 云开发版
// 已迁移至云开发，不再依赖独立 HTTP 后端域名
// cloudEnv 与 app.js 中 wx.cloud.init 保持一致
module.exports = {
  cloudEnv: 'cloud1-d2gek3mad0a97e6a8',
  // domain 保留兼容（部分页面 WXML 中可能引用 imagesDomain 等），
  // 实际网络请求已全部走云函数，不再使用此字段
  domain: ''
};
