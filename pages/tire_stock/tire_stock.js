// 库存总览 + 流水搜索（双Tab）
Page({
  data: {
    activeTab: 'stock', // 'stock' | 'search'

    // 库存 Tab
    stockList: [],
    stockLoading: true,

    // 搜索 Tab
    searchKeyword: '',
    searchType: '',
    searchDateFrom: '',
    searchDateTo: '',
    searchResults: [],
    searchLoading: false,

    // 筛选
    showActionSheet: false,
    actionRecord: null,

    // 一键清空
    _clearing: false
  },

  onShow() {
    this._loadStock()
  },

  // ---- Tab 切换 ----
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    this.setData({ activeTab: tab })
    if (tab === 'stock') {
      this._loadStock()
    }
  },

  // ---- 库存 Tab ----
  _loadStock() {
    this.setData({ stockLoading: true })
    wx.cloud.callFunction({ name: 'getStockList', data: {} }).then(res => {
      if (res.result && res.result.ok) {
        // 只显示有库存的，并附加库存状态计算
        const list = (res.result.list || [])
          .filter(r => r.stock > 0)
          .map(r => {
            const stockRatio = Math.min(Math.round(r.stock / Math.max(r.totalIn, 1) * 100), 100)
            let stockStatus = 'healthy'
            if (r.stock === 0) stockStatus = 'out'
            else if (stockRatio < 50) stockStatus = 'low'
            return { ...r, stockRatio, stockStatus }
          })
        this.setData({ stockList: list, stockLoading: false })
      } else {
        console.error('getStockList 返回异常:', res.result)
        this.setData({ stockList: [], stockLoading: false })
        wx.showToast({ title: res.result?.message || '加载库存失败', icon: 'none' })
      }
    }).catch(err => {
      console.error('getStockList 调用失败:', err)
      this.setData({ stockList: [], stockLoading: false })
      wx.showToast({ title: '加载库存失败，请下拉刷新', icon: 'none' })
    })
  },

  goTireDetail(e) {
    const tireId = e.currentTarget.dataset.tireid
    wx.navigateTo({ url: `/pages/tire_detail/tire_detail?tireId=${tireId}` })
  },

  // ---- 搜索 Tab ----
  onKeywordInput(e) { this.setData({ searchKeyword: e.detail.value }) },
  onTypeChange(e) { this.setData({ searchType: e.currentTarget.dataset.type }) },
  onDateFromChange(e) { this.setData({ searchDateFrom: e.detail.value }) },
  onDateToChange(e) { this.setData({ searchDateTo: e.detail.value }) },

  doSearch() {
    wx.cloud.callFunction({
      name: 'searchRecords',
      data: {
        keyword: this.data.searchKeyword,
        type: this.data.searchType,
        dateFrom: this.data.searchDateFrom,
        dateTo: this.data.searchDateTo
      }
    }).then(res => {
      if (res.result && res.result.ok) {
        this.setData({ searchResults: res.result.list || [] })
      } else {
        console.error('searchRecords 返回异常:', res.result)
        this.setData({ searchResults: [] })
      }
    }).catch(err => {
      console.error('searchRecords 调用失败:', err)
      wx.showToast({ title: '搜索失败，请重试', icon: 'none' })
    })
  },

  // ---- 流水操作 ----
  showActions(e) {
    const record = e.currentTarget.dataset.record
    this.setData({ showActionSheet: true, actionRecord: record })
  },
  closeActions() { this.setData({ showActionSheet: false }) },

  editRecord() {
    const rec = this.data.actionRecord
    this.setData({ showActionSheet: false })
    wx.showToast({ title: '编辑功能：请前往对应页面修改', icon: 'none' })
    // 后续可扩展：跳转 purchase/sale 页面并传入记录ID
  },

  deleteRecord() {
    const rec = this.data.actionRecord
    const isPurchase = rec.recordType === 'purchase'
    wx.showModal({
      title: '确认删除',
      content: isPurchase
        ? '删除此进货单后库存将自动重算。若该进货单已有出库记录则无法删除。'
        : '删除此出货单后库存将自动恢复。',
      success: res => {
        if (!res.confirm) return
        this.setData({ showActionSheet: false })
        wx.showLoading({ title: '删除中…', mask: true })
        wx.cloud.callFunction({
          name: 'deleteRecord',
          data: { id: rec._id, collection: isPurchase ? 'purchase' : 'sales' }
        }).then(r => {
          wx.hideLoading()
          if (r.result && r.result.ok) {
            wx.showToast({ title: '已删除', icon: 'success' })
            this.doSearch()
            this._loadStock()
          } else {
            wx.showToast({ title: r.result.message || '删除失败', icon: 'none', duration: 3000 })
          }
        }).catch(err => {
          wx.hideLoading()
          wx.showToast({ title: '删除失败：' + (err.message || '网络异常'), icon: 'none' })
        })
      }
    })
  },

  // ---- 一键清空（云函数）----

  /** 清空全部进货记录 */
  clearPurchases() {
    if (this.data._clearing) return
    wx.showModal({
      title: '确认清空',
      content: '确认清空所有进货记录？清空后相关库存将归零。此操作不可撤销。',
      success: res => {
        if (!res.confirm) return
        this.setData({ _clearing: true })
        wx.showLoading({ title: '清空中...', mask: true })
        wx.cloud.callFunction({ name: 'clearPurchases' }).then(r => {
          wx.hideLoading()
          this.setData({ _clearing: false })
          if (r.result && r.result.ok) {
            const msg = r.result.failCount
              ? `成功 ${r.result.deletedCount} 条, 失败 ${r.result.failCount} 条`
              : `已清空 ${r.result.deletedCount} 条进货记录`
            wx.showToast({ title: msg, icon: 'success', duration: r.result.failCount ? 3000 : 1500 })
            this.doSearch()
            this._loadStock()
          } else {
            wx.showToast({ title: r.result?.message || '清空失败', icon: 'none' })
          }
        }).catch(err => {
          wx.hideLoading()
          this.setData({ _clearing: false })
          console.error('clearPurchases 调用失败:', err)
          wx.showToast({ title: '清空失败，请重试', icon: 'none' })
        })
      }
    })
  },

  /** 清空全部出货记录 */
  clearSales() {
    if (this.data._clearing) return
    wx.showModal({
      title: '确认清空',
      content: '确认清空所有出货记录？清空后库存将恢复为仅进货数量。此操作不可撤销。',
      success: res => {
        if (!res.confirm) return
        this.setData({ _clearing: true })
        wx.showLoading({ title: '清空中...', mask: true })
        wx.cloud.callFunction({ name: 'clearSales' }).then(r => {
          wx.hideLoading()
          this.setData({ _clearing: false })
          if (r.result && r.result.ok) {
            const msg = r.result.failCount
              ? `成功 ${r.result.deletedCount} 条, 失败 ${r.result.failCount} 条`
              : `已清空 ${r.result.deletedCount} 条出货记录`
            wx.showToast({ title: msg, icon: 'success', duration: r.result.failCount ? 3000 : 1500 })
            this.doSearch()
            this._loadStock()
          } else {
            wx.showToast({ title: r.result?.message || '清空失败', icon: 'none' })
          }
        }).catch(err => {
          wx.hideLoading()
          this.setData({ _clearing: false })
          console.error('clearSales 调用失败:', err)
          wx.showToast({ title: '清空失败，请重试', icon: 'none' })
        })
      }
    })
  },

  /** 重置库存 — 双重确认 */
  resetStock() {
    if (this.data._clearing) return
    wx.showModal({
      title: '⚠️ 重置库存',
      content: '此操作将清空所有进货和出货记录，全部库存归零且无法恢复。确定继续？',
      confirmText: '继续',
      success: res => {
        if (!res.confirm) return
        wx.showModal({
          title: '⚠️ 再次确认',
          content: '此操作不可撤销！所有记录将被物理删除，库存将全部归零。确定执行吗？',
          confirmText: '确认重置',
          confirmColor: '#c0392b',
          success: res2 => {
            if (!res2.confirm) return
            this.setData({ _clearing: true })
            wx.showLoading({ title: '重置中...', mask: true })
            wx.cloud.callFunction({ name: 'resetStock' }).then(r => {
              wx.hideLoading()
              this.setData({ _clearing: false })
              if (r.result && r.result.ok) {
                let msg = `进货 ${r.result.purchaseCount} 条、出货 ${r.result.salesCount} 条已清除`
                if (r.result.purchaseFail || r.result.salesFail) {
                  msg += `\n（进货${r.result.purchaseFail}条、出货${r.result.salesFail}条失败）`
                }
                wx.showToast({ title: '库存已重置', icon: 'success' })
                wx.showModal({ title: '重置完成', content: msg, showCancel: false })
                this.doSearch()
                this._loadStock()
              } else {
                wx.showToast({ title: r.result?.message || '重置失败', icon: 'none' })
              }
            }).catch(err => {
              wx.hideLoading()
              this.setData({ _clearing: false })
              console.error('resetStock 调用失败:', err)
              wx.showToast({ title: '重置失败，请重试', icon: 'none' })
            })
          }
        })
      }
    })
  }
})
