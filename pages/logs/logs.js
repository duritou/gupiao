const { formatTime, MAX_LOG_ENTRIES } = require('../../utils/util')

Page({
  data: {
    logs: []
  },
  onLoad() {
    const rawLogs = wx.getStorageSync('logs') || []
    // 限制展示数量
    const recent = rawLogs.slice(0, MAX_LOG_ENTRIES)
    this.setData({
      logs: recent.map(log => ({
        date: formatTime(new Date(log)),
        timeStamp: log
      }))
    })
  }
})
