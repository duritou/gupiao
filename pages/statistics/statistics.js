// 流水统计页 — 按时间范围展示进销存汇总指标
Page({
  data: {
    // Tab 配置
    tabs: [
      { key: 'today', label: '今日' },
      { key: 'month', label: '近一月' },
      { key: 'year', label: '近一年' },
      { key: 'twoYears', label: '近两年' },
      { key: 'all', label: '全部' }
    ],
    activeTab: 'month',     // 默认近一月
    activeLabel: '近一月',

    // 统计指标
    inQty: 0,
    inAmount: '0.00',
    outQty: 0,
    outAmount: '0.00',

    // 状态
    loading: false,
    loadError: false
  },

  onLoad() {
    this._fetchStats()
  },

  // ---- Tab 切换 ----
  onTabChange(e) {
    const key = e.currentTarget.dataset.key
    if (key === this.data.activeTab) return // 已选中不重复请求

    const tab = this.data.tabs.find(t => t.key === key)
    this.setData({
      activeTab: key,
      activeLabel: tab ? tab.label : ''
    }, () => {
      this._fetchStats()
    })
  },

  // ---- 调用云函数获取统计数据 ----
  _fetchStats() {
    this.setData({ loading: true, loadError: false })

    wx.cloud.callFunction({
      name: 'getStatistics',
      data: { timeRange: this.data.activeTab }
    }).then(res => {
      this.setData({ loading: false })
      if (res.result && res.result.ok) {
        this.setData({
          inQty: res.result.inQty || 0,
          inAmount: (res.result.inAmount || 0).toFixed(2),
          outQty: res.result.outQty || 0,
          outAmount: (res.result.outAmount || 0).toFixed(2)
        })
      } else {
        // 云函数返回异常
        console.error('getStatistics 返回异常:', res.result)
        this.setData({ loadError: true })
        wx.showToast({ title: res.result?.message || '服务异常，请重试', icon: 'none' })
      }
    }).catch(err => {
      this.setData({ loading: false, loadError: true })
      console.error('getStatistics 调用失败:', err)

      // 三档错误提示
      const errMsg = err.errMsg || ''
      if (errMsg.includes('not found') || errMsg.includes('is not defined')) {
        wx.showToast({ title: '云函数未部署，请上传云函数', icon: 'none', duration: 2500 })
      } else if (errMsg.includes('timeout') || errMsg.includes('超时')) {
        wx.showToast({ title: '请求超时，请重试', icon: 'none' })
      } else {
        wx.showToast({ title: '服务异常，请重试', icon: 'none' })
      }
    })
  }
})
