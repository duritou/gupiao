// 酒店模块网络层 — 云开发版（替换原 HTTP REST API）
// 所有请求通过 wx.cloud.callFunction('hotelApi', { action, ... }) 转发
// 返回格式兼容原 res.data.code / res.data.data 结构，页面代码无需改动

// 登录就绪 Promise 引用（由 app.js 在 onLaunch 中设置）
var loginReady = null;

function ensureLogin() {
  if (loginReady) {
    return loginReady;
  }
  // 健壮性：即使模块先于 app.js 加载，首次调用时也能拿到
  var app = getApp();
  if (app && app.hotelLoginReady) {
    loginReady = app.hotelLoginReady;
  } else {
    // 极端情况：app 尚未初始化，直接 resolve
    loginReady = Promise.resolve();
  }
  return loginReady;
}

function request(requestHandler) {
  var data = requestHandler.data || {};
  var url = requestHandler.url;
  var method = requestHandler.method || 'GET';

  // 登录接口本身不等待登录完成（否则死锁）
  var isLoginCall = (url === 'login' && method.toUpperCase() === 'POST');

  function doRequest() {
    wx.showLoading({ title: '加载中' });

    wx.cloud.callFunction({
      name: 'hotelApi',
      data: {
        action: url,        // 对应原 HTTP 路径，如 'home'、'room?startTime=...'
        method: method,
        payload: data       // 原 request body / query params
      }
    }).then(function (cloudRes) {
      wx.hideLoading();
      // 云函数返回 { code, data, message }，包装为兼容原 res.data 结构
      var result = cloudRes.result || {};
      var wrappedRes = {
        data: {
          code: result.code,
          data: result.data,
          message: result.message || ''
        }
      };
      if (typeof requestHandler.success === 'function') {
        requestHandler.success(wrappedRes);
      }
    }).catch(function (err) {
      wx.hideLoading();
      console.error('云函数 hotelApi 调用失败:', err);
      if (typeof requestHandler.fail === 'function') {
        requestHandler.fail();
      }
    });
  }

  if (isLoginCall) {
    // 登录请求：直接发送，不等待
    doRequest();
  } else {
    // 业务请求：等待登录完成后再发送
    ensureLogin().then(function () {
      doRequest();
    }).catch(function () {
      wx.hideLoading();
      if (typeof requestHandler.fail === 'function') {
        requestHandler.fail();
      }
    });
  }
}

module.exports = {
  request: request
};
