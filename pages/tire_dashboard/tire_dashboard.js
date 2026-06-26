// 轮胎仪表盘 — 今日统计 + 快捷入口（非阻塞加载，先展示缓存/默认值）
Page({
  data: {
    loading: false,
    today: '',
    purchaseTotal: '0.00',
    saleTotalQty: 0
  },

  onLoad() {
    const today = new Date().toISOString().slice(0, 10)
    // 优先展示本地缓存（同一天内瞬时呈现；onShow 会紧随其后调用 _fetchStats 刷新）
    const cache = wx.getStorageSync('__dashboard_cache__') || {}
    if (cache.date === today && (cache.purchaseTotal || cache.saleTotalQty !== undefined)) {
      this.setData({
        today,
        purchaseTotal: cache.purchaseTotal || '0.00',
        saleTotalQty: cache.saleTotalQty || 0
      })
    } else {
      this.setData({ today })
    }
  },

  onShow() {
    this._fetchStats()
  },

  _fetchStats() {
    const today = new Date().toISOString().slice(0, 10)
    // 不再设 loading: true — 首次加载用户看到默认值/缓存，后台静默更新
    wx.cloud.callFunction({
      name: 'dashboardStats',
      data: { date: today }
    }).then(res => {
      const data = res.result || {}
      if (data.ok === false) {
        console.error('dashboardStats 返回异常:', data.message || data)
      }
      const stats = {
        purchaseTotal: data.purchaseTotal || '0.00',
        saleTotalQty: data.saleTotalQty || 0
      }
      this.setData({ ...stats, today })
      // 缓存当天数据
      wx.setStorageSync('__dashboard_cache__', { date: today, ...stats })
    }).catch(err => {
      console.error('dashboardStats 调用失败:', err)
      const msg = err.errMsg || ''
      if (msg.indexOf('function not found') !== -1) {
        wx.showToast({ title: '云函数未部署，请上传云函数', icon: 'none' })
      } else if (msg.indexOf('timeout') !== -1) {
        wx.showToast({ title: '网络超时，请重试', icon: 'none' })
      } else {
        wx.showToast({ title: '服务异常: ' + (err.errMsg || '未知错误'), icon: 'none' })
      }
    })
  },

  // 快捷入口
  goPurchase() { wx.navigateTo({ url: '/pages/tire_purchase/tire_purchase' }) },
  goSale() { wx.navigateTo({ url: '/pages/tire_sale/tire_sale' }) },
  goStock() { wx.navigateTo({ url: '/pages/tire_stock/tire_stock' }) },
  goExport() { wx.navigateTo({ url: '/pages/tire_export/tire_export' }) },
  goStatistics() { wx.navigateTo({ url: '/pages/statistics/statistics' }) }
})
