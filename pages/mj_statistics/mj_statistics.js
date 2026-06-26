// 麻将个人数据统计页 — 汇总当前用户所有已结算对局的 6 项指标
Page({
  data: {
    // 统计指标
    totalGames: 0,        // 总对局数
    totalScore: 0,        // 总得分
    avgScore: '0.00',     // 场均得分
    winRate: '0.0',       // 胜率
    bestScore: 0,         // 最高得分
    worstScore: 0,        // 最低得分
    lastGameTime: '',     // 最近对局时间（格式化后）

    // 对局历史列表
    historyList: [],

    // UI 状态
    loading: true,
    loadError: false,
    isEmpty: false
  },

  onLoad: function () {
    this._fetchStats()
  },

  onShow: function () {
    // 首次加载后不重复请求（onLoad 已触发）
    if (!this.data.loading && !this.data.loadError) return
    this._fetchStats()
  },

  onPullDownRefresh: function () {
    this._fetchStats()
  },

  /** 调用云函数获取统计数据 */
  _fetchStats: function () {
    var self = this

    // 用户已清除记录 → 跳过云端拉取，展示空数据
    if (wx.getStorageSync('__mj_data_cleared__')) {
      self.setData({
        loading: false,
        isEmpty: true,
        totalGames: 0,
        totalScore: 0,
        avgScore: '0.00',
        winRate: '0.0',
        bestScore: 0,
        worstScore: 0,
        lastGameTime: '',
        historyList: []
      })
      return
    }

    self.setData({ loading: true, loadError: false, isEmpty: false })

    wx.cloud.callFunction({
      name: 'getMjStats',
      data: {}
    }).then(function (res) {
      self.setData({ loading: false })
      wx.stopPullDownRefresh()

      if (res.result && res.result.ok) {
        var result = res.result
        self.setData({
          totalGames: result.totalGames,
          totalScore: result.totalScore,
          avgScore: (result.avgScore !== undefined ? result.avgScore : 0).toFixed(2),
          winRate: (result.winRate !== undefined ? result.winRate : 0).toFixed(1),
          bestScore: result.bestScore,
          worstScore: result.worstScore,
          lastGameTime: self._formatTime(result.lastGameTime),
          historyList: (result.history || []).map(function (item) {
            item.settleTimeFormatted = self._formatTime(item.settleTime)
            return item
          }),
          isEmpty: result.totalGames === 0
        })
      } else {
        self.setData({ loadError: true })
        wx.showToast({
          title: (res.result && res.result.message) || '服务异常，请重试',
          icon: 'none'
        })
      }
    }).catch(function (err) {
      self.setData({ loading: false, loadError: true })
      wx.stopPullDownRefresh()
      console.error('[mj_statistics] 调用 getMjStats 失败:', err)

      var errMsg = err.errMsg || ''
      if (errMsg.indexOf('not found') > -1 || errMsg.indexOf('is not defined') > -1) {
        wx.showToast({ title: '云函数未部署，请上传云函数', icon: 'none', duration: 2500 })
      } else if (errMsg.indexOf('timeout') > -1 || errMsg.indexOf('超时') > -1) {
        wx.showToast({ title: '请求超时，请重试', icon: 'none' })
      } else {
        wx.showToast({ title: '服务异常，请重试', icon: 'none' })
      }
    })
  },

  /** 格式化时间戳 → YYYY-MM-DD HH:MM */
  _formatTime: function (ts) {
    if (!ts) return ''
    var d = new Date(ts)
    if (isNaN(d.getTime())) return ''
    var pad = function (n) { return n < 10 ? '0' + n : n }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
  }
})
