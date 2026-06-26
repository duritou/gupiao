// 轮胎详情 — 基本信息 + 库存 + 价格趋势 + 流水
Page({
  data: {
    tireId: '',
    tire: null,
    stock: 0,
    lastPrice: 0,
    priceHistory: [],
    purchase: [],
    sales: [],
    loading: true,
    activeTab: 'purchase', // 'purchase' | 'sale' | 'price'

    // 管理模式（单选/多选删除）
    manageMode: false,
    selectedIds: {},
    selectedCount: 0,
    _deleting: false
  },

  onLoad(options) {
    const tireId = options.tireId
    if (!tireId) {
      wx.showToast({ title: '缺少轮胎ID', icon: 'none' })
      return
    }
    this.setData({ tireId })
    this._load()
  },

  onShow() {
    if (this.data.tireId) this._load()
  },

  _load() {
    this.setData({ loading: true })
    wx.cloud.callFunction({ name: 'getTireProfile', data: { tireId: this.data.tireId } }).then(res => {
      if (res.result && res.result.ok) {
        const d = res.result
        const purchase = d.purchase || []
        this.setData({
          tire: d.tire,
          stock: d.stock,
          lastPrice: d.lastPrice,
          priceHistory: d.priceHistory || [],
          purchase,
          sales: d.sales || [],
          loading: false
        })
        // 转换进货记录中的 cloud:// 图片为临时 HTTP URL
        this._convertImages(purchase)
      } else {
        console.error('getTireProfile 返回异常:', res.result)
        wx.showToast({ title: res.result?.message || '加载失败', icon: 'none' })
        this.setData({ loading: false })
      }
    }).catch(err => {
      console.error('getTireProfile 调用失败:', err)
      this.setData({ loading: false })
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

  // 将进货记录中的 cloud:// 图片转为临时 HTTP URL
  // 同时支持 imageList（多图数组）和 photo（单张首图）两种字段
  _convertImages(purchaseList) {
    const fileIDs = []
    const seen = {} // 去重
    purchaseList.forEach(p => {
      // 收集 imageList 中的 cloud:// fileID
      if (p.imageList && p.imageList.length > 0) {
        p.imageList.forEach(fid => {
          if (fid && fid.startsWith('cloud://') && !seen[fid]) {
            fileIDs.push(fid)
            seen[fid] = true
          }
        })
      }
      // 兜底：如果 imageList 为空但 photo 字段有值，也纳入转换
      if ((!p.imageList || p.imageList.length === 0) && p.photo && p.photo.startsWith('cloud://') && !seen[p.photo]) {
        fileIDs.push(p.photo)
        seen[p.photo] = true
      }
    })
    console.log('[tire_detail] 待转换图片 fileID 数量:', fileIDs.length)
    if (fileIDs.length === 0) return

    wx.cloud.getTempFileURL({ fileList: fileIDs }).then(res => {
      console.log('[tire_detail] getTempFileURL 返回:', res.fileList ? res.fileList.length : 0, '个结果')
      const urlMap = {}
      ;(res.fileList || []).forEach(f => {
        if (f.tempFileURL) {
          urlMap[f.fileID] = f.tempFileURL
        } else {
          console.warn('[tire_detail] 转换失败 fileID:', f.fileID, 'errMsg:', f.errMsg)
        }
      })
      // 替换每个进货记录中的图片
      const updated = this.data.purchase.map(p => {
        const imageUrls = []
        // 优先用 imageList
        if (p.imageList && p.imageList.length > 0) {
          p.imageList.forEach(fid => {
            const url = urlMap[fid]
            if (url) imageUrls.push(url)
          })
        }
        // 兜底：只有 photo 的情况
        if (imageUrls.length === 0 && p.photo) {
          const url = urlMap[p.photo]
          if (url) imageUrls.push(url)
        }
        return { ...p, imageUrls }
      })
      this.setData({ purchase: updated })
    }).catch(err => {
      console.error('[tire_detail] getTempFileURL 失败:', err)
    })
  },

  switchTab(e) {
    // 管理模式中切 Tab → 先退出管理模式
    if (this.data.manageMode) {
      this.setData({ manageMode: false, selectedIds: {}, selectedCount: 0 })
    }
    this.setData({ activeTab: e.currentTarget.dataset.tab })
  },

  goBack() {
    wx.navigateBack()
  },

  // 点击照片预览大图
  previewImage(e) {
    const { urls, current } = e.currentTarget.dataset
    wx.previewImage({ urls, current })
  },

  // ==================== 管理模式（单选/多选删除） ====================

  // 切换管理模式
  toggleManageMode() {
    const entering = !this.data.manageMode
    this.setData({
      manageMode: entering,
      selectedIds: {},
      selectedCount: 0
    })
  },

  // 勾选/取消单条记录（catchtap 防冒泡）
  toggleSelect(e) {
    const id = e.currentTarget.dataset.id
    const selectedIds = { ...this.data.selectedIds }
    if (selectedIds[id]) {
      delete selectedIds[id]
    } else {
      selectedIds[id] = true
    }
    const selectedCount = Object.keys(selectedIds).length
    this.setData({ selectedIds, selectedCount })
  },

  // 全选 / 取消全选
  selectAll() {
    const list = this.data.activeTab === 'purchase' ? this.data.purchase : this.data.sales
    const allIds = list.map(r => r._id)
    // 已全选则取消全部
    if (this.data.selectedCount === allIds.length && allIds.length > 0) {
      this.setData({ selectedIds: {}, selectedCount: 0 })
      return
    }
    const selectedIds = {}
    allIds.forEach(id => { selectedIds[id] = true })
    this.setData({ selectedIds, selectedCount: allIds.length })
  },

  // 批量删除确认
  batchDelete() {
    if (this.data._deleting || this.data.selectedCount === 0) return

    const collection = this.data.activeTab === 'purchase' ? 'purchase' : 'sales'
    const count = this.data.selectedCount
    const isPurchase = collection === 'purchase'

    const content = isPurchase
      ? `确认删除选中的 ${count} 条进货记录？若某条已有出库则无法删除。`
      : `确认删除选中的 ${count} 条出库记录？删除后对应库存将自动恢复。`

    wx.showModal({
      title: '确认删除',
      content,
      confirmText: '删除',
      confirmColor: '#c0392b',
      success: res => {
        if (!res.confirm) return
        const ids = Object.keys(this.data.selectedIds)
        this._doBatchDelete(ids, collection)
      }
    })
  },

  // 执行批量删除
  _doBatchDelete(ids, collection) {
    this.setData({ _deleting: true })
    wx.showLoading({ title: '删除中…', mask: true })

    const tasks = ids.map(id =>
      wx.cloud.callFunction({ name: 'deleteRecord', data: { id, collection } })
        .then(r => (r.result && r.result.ok) ? { ok: true } : { ok: false, msg: r.result?.message || '删除失败' })
        .catch(err => ({ ok: false, msg: err.message || '网络异常' }))
    )

    Promise.all(tasks).then(results => {
      wx.hideLoading()
      const okCount = results.filter(r => r.ok).length
      const failCount = results.length - okCount

      let toastMsg = ''
      if (failCount === 0) {
        toastMsg = `已删除 ${okCount} 条`
      } else if (okCount === 0) {
        toastMsg = '删除失败，请重试'
      } else {
        toastMsg = `成功 ${okCount} 条，失败 ${failCount} 条`
      }

      wx.showToast({ title: toastMsg, icon: failCount === 0 ? 'success' : 'none', duration: 2500 })

      // 退出管理模式并刷新
      this.setData({ manageMode: false, selectedIds: {}, selectedCount: 0, _deleting: false })
      this._load()
    })
  }
})
