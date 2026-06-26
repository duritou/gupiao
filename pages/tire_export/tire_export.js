// 数据导出 — 按条件生成 CSV
Page({
  data: {
    exportType: '', // '' all | 'purchase' | 'sale'
    dateFrom: '',
    dateTo: '',
    exporting: false,
    exportResult: null
  },

  setType(e) {
    this.setData({ exportType: e.currentTarget.dataset.type })
  },

  onDateFromChange(e) { this.setData({ dateFrom: e.detail.value }) },
  onDateToChange(e) { this.setData({ dateTo: e.detail.value }) },

  doExport() {
    this.setData({ exporting: true, exportResult: null })
    wx.showLoading({ title: '生成CSV中...' })

    wx.cloud.callFunction({
      name: 'exportCSV',
      data: {
        type: this.data.exportType,
        dateFrom: this.data.dateFrom,
        dateTo: this.data.dateTo
      }
    }).then(res => {
      wx.hideLoading()
      if (res.result && res.result.ok) {
        this.setData({
          exporting: false,
          exportResult: res.result
        })
      } else {
        this.setData({ exporting: false })
        wx.showToast({ title: '导出失败', icon: 'none' })
      }
    }).catch(err => {
      wx.hideLoading()
      console.error('exportCSV 调用失败:', err)
      this.setData({ exporting: false })
      wx.showToast({ title: '导出失败，请重试', icon: 'none' })
    })
  },

  // 复制下载链接
  copyLink() {
    if (!this.data.exportResult) return
    wx.setClipboardData({
      data: this.data.exportResult.fileID,
      success: () => {
        wx.showToast({ title: '文件ID已复制', icon: 'success' })
      }
    })
  },

  // 预览前10行（通过打开文件ID）
  preview() {
    if (!this.data.exportResult) return
    wx.cloud.downloadFile({
      fileID: this.data.exportResult.fileID,
      success: res => {
        wx.openDocument({
          filePath: res.tempFilePath,
          showMenu: true,
          success: () => {},
          fail: () => {
            wx.showToast({ title: '预览失败', icon: 'none' })
          }
        })
      },
      fail: () => {
        wx.showToast({ title: '下载失败，请检查云存储', icon: 'none' })
      }
    })
  }
})
