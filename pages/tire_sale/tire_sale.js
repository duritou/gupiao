// 出库登记 — 品牌筛选 → 库存列表 → 出库表单 → FIFO 自动分配
// 支持扫码出库：扫码 → 云函数解析 → 自动匹配库存
const { parseScanCode } = require('../../utils/scanParser')

Page({
  data: {
    formDate: '',

    // 品牌选择（仅显示有库存的品牌）
    brandNames: ['请选择品牌'],
    brandIdx: 0,
    selectedBrandId: '',
    brandsLoading: true,       // 品牌列表加载中

    // 库存列表
    stockList: [],
    filteredStockList: [],    // 搜索过滤后的列表
    stockLoading: false,
    stockKeyword: '',          // 库存内搜索关键词

    // 扫码出库
    scanNote: '',              // 扫码识别结果提示
    scanFilter: null,          // 扫码解析出的规格（用于过滤库存）
    showManualUrlModal: false, // 手动粘贴URL弹窗
    manualUrl: '',
    manualUrlError: '',

    // 出库表单（选中条目后展示）
    selectedItem: null,       // 当前选中的库存条目
    showSaleForm: false,      // 是否展示出库表单
    formQty: '1',
    formUnitPrice: '',
    formPlate: '',
    formCustomer: '',
    formNote: '',
    formTotal: '0.00',
    formOutType: 'sales',

    submitting: false,
    stockListExpanded: false, // 库存列表折叠/展开状态
    plateOcrStatus: 'idle',   // idle | loading | success | error
    plateOcrResult: ''        // 成功时暂存识别到的车牌号，用于按钮展示
  },

  onLoad() {
    this.setData({ formDate: new Date().toISOString().slice(0, 10) })
    this._loadBrandsWithStock()
  },

  onShow() {
    // 每次进入页面刷新品牌列表（防止首次加载未完成、或出库后库存变化）
    if (!this.data.brandsLoading && this.data.brandNames.length <= 1) {
      this._loadBrandsWithStock()
    }
  },

  onHide() {
    // 清除 OCR 状态复位定时器
    if (this._ocrResetTimer) {
      clearTimeout(this._ocrResetTimer)
      this._ocrResetTimer = null
    }
  },

  // ---- Step 1: 加载有库存的品牌列表 ----
  _loadBrandsWithStock() {
    this.setData({ brandsLoading: true })
    wx.cloud.callFunction({ name: 'getStockByBrand', data: {} }).then(res => {
      this.setData({ brandsLoading: false })
      if (res.result && res.result.ok) {
        const brands = res.result.brands || []
        console.log('getStockByBrand 品牌列表:', brands)
        const names = ['请选择品牌', ...brands]
        this.setData({ brandNames: names })
        if (brands.length === 0) {
          console.log('暂无有库存的品牌')
        }
      } else {
        console.error('getStockByBrand 品牌列表异常:', res.result)
      }
    }).catch(err => {
      this.setData({ brandsLoading: false })
      console.error('getStockByBrand 调用失败:', err)
    })
  },

  onBrandChange(e) {
    const idx = Number(e.detail.value)
    const brandName = idx > 0 ? this.data.brandNames[idx] : ''
    this.setData({
      brandIdx: idx,
      selectedBrandId: brandName,
      stockList: [],
      filteredStockList: [],
      stockKeyword: '',
      selectedItem: null,
      showSaleForm: false,
      scanFilter: null,     // 手动切品牌时清除扫码过滤
      scanNote: '',
      stockListExpanded: false
    })

    if (idx === 0) {
      // "请选择品牌" — 不加载
      return
    }

    this._loadStockByBrand(brandName)
  },

  // ---- Step 2: 加载该品牌的库存列表 ----
  _loadStockByBrand(brandName) {
    if (!brandName) return
    this.setData({ stockLoading: true })

    wx.cloud.callFunction({
      name: 'getStockByBrand',
      data: { brandId: brandName }
    }).then(res => {
      this.setData({ stockLoading: false })
      if (res.result && res.result.ok) {
        const list = res.result.list || []
        this.setData({ stockList: list, filteredStockList: list })
        // 如果是从扫码触发的加载，自动过滤匹配规格
        if (this.data.scanFilter) {
          this._applyScanFilter(list)
        } else if (list.length === 0) {
          wx.showToast({ title: '该品牌暂无库存', icon: 'none' })
        }
      } else {
        console.error('getStockByBrand 库存列表异常:', res.result)
        wx.showToast({ title: res.result?.message || '加载库存失败', icon: 'none' })
      }
    }).catch(err => {
      this.setData({ stockLoading: false })
      console.error('getStockByBrand 调用失败:', err)
      wx.showToast({ title: '加载库存失败，请重试', icon: 'none' })
    })
  },

  // 扫码后自动过滤库存：按 size → pattern 匹配，单条命中自动选中
  _applyScanFilter(list) {
    const filter = this.data.scanFilter
    if (!filter || !list.length) return

    // 按规格+花纹匹配（大小写不敏感）
    const scanSize = (filter.size || '').toLowerCase()
    const scanPattern = (filter.pattern || '').toLowerCase()

    let filtered = list
    if (scanSize) {
      filtered = filtered.filter(item =>
        (item.size || '').toLowerCase().includes(scanSize) ||
        scanSize.includes((item.size || '').toLowerCase())
      )
    }
    if (scanPattern && filtered.length > 0) {
      const patternFiltered = filtered.filter(item =>
        (item.pattern || '').toLowerCase().includes(scanPattern) ||
        scanPattern.includes((item.pattern || '').toLowerCase())
      )
      if (patternFiltered.length > 0) filtered = patternFiltered
    }

    this.setData({ filteredStockList: filtered, stockKeyword: '', stockListExpanded: false })

    // 清空出库表单
    this.setData({
      selectedItem: null,
      showSaleForm: false,
      formQty: '1', formUnitPrice: '', formCustomer: '', formNote: '', formTotal: '0.00'
    })

    if (filtered.length === 1) {
      // 唯一条目 → 自动选中
      const item = filtered[0]
      this.setData({
        selectedItem: item,
        showSaleForm: true,
        formQty: '1',
        formUnitPrice: String(item.lastPrice || ''),
        formCustomer: '',
        formNote: '',
        formTotal: '0.00'
      })
      wx.showToast({ title: '已自动匹配: ' + (item.size || '') + ' ' + (item.pattern || ''), icon: 'success' })
    } else if (filtered.length === 0) {
      wx.showToast({ title: '未找到匹配库存', icon: 'none', duration: 2500 })
    } else {
      wx.showToast({ title: `找到 ${filtered.length} 条匹配，请选择`, icon: 'none' })
    }
  },

  // ---- 库存内搜索 ----
  onStockSearch(e) {
    const keyword = (e.detail.value || '').trim().toLowerCase()
    this.setData({ stockKeyword: keyword })
    if (!keyword) {
      this.setData({ filteredStockList: this.data.stockList, stockListExpanded: false })
      return
    }
    const filtered = this.data.stockList.filter(item => {
      const text = `${item.size || ''} ${item.pattern || ''} ${item.ply || ''} ${item.loadIndex || ''}`.toLowerCase()
      return text.includes(keyword)
    })
    this.setData({ filteredStockList: filtered, stockListExpanded: false })
  },

  // 库存列表折叠/展开
  onToggleStockExpand() {
    this.setData({ stockListExpanded: !this.data.stockListExpanded })
  },

  // ---- Step 3: 选择库存条目，展开出库表单 ----
  onSelectItem(e) {
    const tireId = e.currentTarget.dataset.id
    const item = this.data.stockList.find(s => s.tireId === tireId)
    if (!item) return

    this.setData({
      selectedItem: item,
      showSaleForm: true,
      formQty: '1',
      formUnitPrice: String(item.lastPrice || ''),
      formCustomer: '',
      formNote: '',
      formTotal: '0.00'
    })
  },

  // 取消出库表单
  onCancelSale() {
    this.setData({
      selectedItem: null,
      showSaleForm: false,
      formQty: '1',
      formUnitPrice: '',
      formPlate: '',
      formCustomer: '',
      formNote: '',
      formTotal: '0.00'
    })
  },

  // ---- 表单字段 ----
  onDateChange(e) {
    this.setData({ formDate: e.detail.value })
  },

  onQtyInput(e) {
    const value = e.detail.value
    this.setData({ formQty: value }, () => {
      this._calcTotal()
    })
  },

  onQtyBlur(e) {
    const value = Number(e.detail.value)
    const max = this.data.selectedItem ? this.data.selectedItem.totalStock : 0
    if (value > max) {
      wx.showToast({ title: `不能超过库存数量: ${max}`, icon: 'none' })
      this.setData({ formQty: String(max) }, () => {
        this._calcTotal()
      })
    }
    if (value <= 0 && e.detail.value !== '') {
      wx.showToast({ title: '数量必须大于0', icon: 'none' })
      this.setData({ formQty: '1' })
    }
  },

  onPriceInput(e) {
    this.setData({ formUnitPrice: e.detail.value }, () => {
      this._calcTotal()
    })
  },

  // ---- 车牌虚拟键盘事件 ----
  onPlateInput(e) {
    this.setData({ formPlate: e.detail.value })
  },

  onPlateComplete(e) {
    // 车牌输入完成时自动记录
    this.setData({ formPlate: e.detail.value })
  },

  onPlateClear() {
    this.setData({ formPlate: '' })
  },

  // ---- 拍照 OCR 识别车牌 ----
  onPlateOCR() {
    if (this.data.plateOcrStatus === 'loading') return
    wx.showActionSheet({
      itemList: ['拍照', '从手机相册选择'],
      success: res => {
        const sourceType = res.tapIndex === 0 ? ['camera'] : ['album']
        this._doPlateOCR(sourceType)
      },
      fail: () => {} // 用户取消
    })
  },

  _doPlateOCR(sourceType) {
    // 进入 loading 态
    this.setData({ plateOcrStatus: 'loading', plateOcrResult: '' })
    wx.showLoading({ title: '识别中…', mask: true })

    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: sourceType,
      success: chooseRes => {
        const tempPath = chooseRes.tempFilePaths[0]

        // 上传到云存储 → 调 ocrPlate 云函数
        const cloudPath = `ocr_plate/${Date.now()}_${Math.random().toString(36).slice(2, 8)}.jpg`
        wx.cloud.uploadFile({
          cloudPath,
          filePath: tempPath,
          success: uploadRes => {
            wx.cloud.callFunction({
              name: 'ocrPlate',
              data: { imgUrl: uploadRes.fileID },
              success: callRes => {
                wx.hideLoading()
                const result = callRes.result
                if (result.code === 0) {
                  const plateNumber = result.data.plateNumber
                  this.setData({
                    formPlate: plateNumber,
                    plateOcrStatus: 'success',
                    plateOcrResult: plateNumber
                  })
                  wx.showToast({ title: `已识别: ${plateNumber}`, icon: 'success' })
                  // 3s 后自动恢复 idle 态
                  this._ocrResetTimer = setTimeout(() => {
                    this.setData({ plateOcrStatus: 'idle' })
                  }, 3000)
                } else {
                  this.setData({ plateOcrStatus: 'error' })
                  wx.showToast({ title: result.msg || '识别失败', icon: 'none', duration: 2500 })
                }
              },
              fail: err => {
                wx.hideLoading()
                this.setData({ plateOcrStatus: 'error' })
                console.error('ocrPlate 云函数调用失败:', err)
                wx.showToast({ title: '识别服务异常，请手动输入', icon: 'none', duration: 2500 })
              }
            })
          },
          fail: err => {
            wx.hideLoading()
            this.setData({ plateOcrStatus: 'error' })
            console.error('图片上传失败:', err)
            wx.showToast({ title: '图片上传失败', icon: 'none' })
          }
        })
      },
      fail: err => {
        this.setData({ plateOcrStatus: 'idle' })
        wx.hideLoading()
        if (err.errMsg && !err.errMsg.includes('cancel')) {
          wx.showToast({ title: '选图失败', icon: 'none' })
        }
      }
    })
  },

  onCustomerInput(e) {
    this.setData({ formCustomer: e.detail.value })
  },

  onNoteInput(e) {
    this.setData({ formNote: e.detail.value })
  },

  onOutTypeChange(e) {
    this.setData({ formOutType: e.currentTarget.dataset.type })
  },

  _calcTotal() {
    const qty = Number(this.data.formQty) || 0
    const price = Number(this.data.formUnitPrice) || 0
    this.setData({ formTotal: (qty * price).toFixed(2) })
  },

  // ---- Step 4: 提交出库（FIFO 自动分配）----
  submit() {
    if (this.data.submitting) return
    const { selectedItem, formQty, formUnitPrice, formPlate, formCustomer, formDate, formOutType, formNote } = this.data

    // 收集所有校验错误（按页面从上到下的顺序）
    const errors = []

    // 1. 品牌
    if (this.data.brandIdx === 0) {
      errors.push({ msg: '请选择品牌', field: 'field-brand' })
    } else if (!selectedItem) {
      // 2. 库存条目
      errors.push({ msg: '请选择库存条目', field: 'field-stock' })
    }

    // 3. 出库数量（仅在已选库存条目后校验，避免 selectedItem 为 null）
    if (selectedItem) {
      const qtyNum = Number(formQty)
      if (!formQty || qtyNum <= 0) {
        errors.push({ msg: '请输入有效的出库数量', field: 'field-qty' })
      } else if (qtyNum > selectedItem.totalStock) {
        errors.push({ msg: `库存不足，当前库存: ${selectedItem.totalStock}`, field: 'field-qty' })
      }
    }

    // 4. 车牌号
    if (!formPlate || !formPlate.trim()) {
      errors.push({ msg: '请填写车牌号', field: 'field-plate' })
    }

    // 有未填项 → 汇总提示并滚动到第一个缺失字段
    if (errors.length > 0) {
      const errorMsgs = errors.map((e, i) => `${i + 1}. ${e.msg}`).join('\n')
      wx.showModal({
        title: '请完善以下信息',
        content: errorMsgs,
        showCancel: false,
        confirmText: '知道了',
        success: () => {
          const first = errors[0]
          if (first.field) {
            wx.pageScrollTo({ selector: `#${first.field}`, duration: 300 })
          }
        }
      })
      return
    }

    this.setData({ submitting: true })
    wx.showLoading({ title: '提交中...', mask: true })

    // 不传 batches，createSale 自动 FIFO 分配
    wx.cloud.callFunction({
      name: 'createSale',
      data: {
        tireId: selectedItem.tireId,
        customer: formCustomer.trim(),
        plate: formPlate.trim(),
        qty: qtyNum,
        unitCost: selectedItem.lastPrice || 0,
        unitPrice: Number(formUnitPrice) || 0,
        outType: formOutType,
        date: formDate,
        note: formNote
      }
    }).then(res => {
      wx.hideLoading()
      this.setData({ submitting: false })
      if (res.result && res.result.ok) {
        wx.showToast({ title: '出库登记成功', icon: 'success' })
        wx.showModal({
          title: '操作成功',
          content: '是否继续出库？',
          confirmText: '继续',
          cancelText: '返回首页',
          success: r => {
            if (r.confirm) {
              this._resetForm()
              // 刷新当前品牌库存
              if (this.data.selectedBrandId) {
                this._loadStockByBrand(this.data.selectedBrandId)
              }
            } else {
              wx.navigateBack()
            }
          }
        })
      } else {
        wx.showToast({ title: res.result.message || '提交失败', icon: 'none', duration: 3000 })
      }
    }).catch(err => {
      wx.hideLoading()
      this.setData({ submitting: false })
      console.error('createSale 调用失败:', err)
      wx.showToast({ title: '提交失败，请重试', icon: 'none' })
    })
  },

  _resetForm() {
    this.setData({
      selectedItem: null,
      showSaleForm: false,
      formQty: '1',
      formUnitPrice: '',
      formPlate: '',
      formCustomer: '',
      formNote: '',
      formTotal: '0.00',
      submitting: false,
      plateOcrStatus: 'idle',
      plateOcrResult: '',
      scanFilter: null,
      scanNote: ''
    })
  },

  // ==================== 扫码出库 ====================
  scanCode() {
    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['qrCode'],
      autoZoom: true,
      barCodeEnhance: true,
      success: res => {
        const code = res.result
        if (!code) {
          wx.showToast({ title: '扫码内容为空', icon: 'none' })
          return
        }
        this._invokeParseTireCode(code)
      },
      fail: () => {
        // 扫码失败 → 弹出手动粘贴URL对话框
        this.setData({ showManualUrlModal: true, manualUrl: '', manualUrlError: '' })
      }
    })
  },

  // 统一解析入口：调用 parseTireCode 云函数
  _invokeParseTireCode(code) {
    wx.showLoading({ title: '解析中...', mask: true })

    wx.cloud.callFunction({ name: 'parseTireCode', data: { url: code } }).then(cfRes => {
      wx.hideLoading()
      const result = cfRes.result
      if (result && result.code === 0 && result.data) {
        this._onScanParsed(result.data)
      } else {
        const msg = (result && result.msg) || '无法识别轮胎信息'
        wx.showToast({ title: msg, icon: 'none', duration: 2500 })
      }
    }).catch(err => {
      wx.hideLoading()
      console.error('parseTireCode 调用失败，使用本地解析兜底:', err)
      this._localParseFallback(code)
    })
  },

  // 本地 scanParser 兜底解析（云函数不可用时）
  _localParseFallback(code) {
    wx.hideLoading()
    const parsed = parseScanCode(code)
    if (parsed.size || parsed.pattern) {
      this._onScanParsed({
        brand: parsed.brand || '',
        size: parsed.size || parsed.spec || '',
        pattern: parsed.pattern || '',
        ply: parsed.ply || '',
        loadSpeed: parsed.loadIndex || parsed.load || ''
      })
      wx.showToast({ title: '本地识别成功，请核对', icon: 'success' })
    } else {
      wx.showToast({ title: '无法识别，请手动选择', icon: 'none', duration: 2500 })
    }
  },

  // 扫码解析成功 → 自动匹配库存
  _onScanParsed(data) {
    const brand = data.brand || ''
    const size = data.size || data.spec || ''
    const pattern = data.pattern || ''
    const serialNo = data.serialNo || ''

    // 保存扫码过滤条件
    this.setData({
      scanFilter: { brand, size, pattern, ply: data.ply || '', loadSpeed: data.loadSpeed || data.loadIndex || '' },
      scanNote: '已扫描: ' + [brand, size, pattern].filter(Boolean).join(' ') + (serialNo ? ' | ' + serialNo : '')
    })

    // 在已加载的品牌列表中匹配品牌
    if (brand && this.data.brandNames.length > 1) {
      const brandIdx = this.data.brandNames.findIndex(b =>
        b === brand || b.includes(brand) || brand.includes(b)
      )
      if (brandIdx > 0) {
        // 自动切换品牌并加载库存（加载完成后 _applyScanFilter 自动过滤）
        const brandName = this.data.brandNames[brandIdx]
        this.setData({
          brandIdx,
          selectedBrandId: brandName,
          stockList: [],
          filteredStockList: [],
          stockKeyword: '',
          selectedItem: null,
          showSaleForm: false
        })
        this._loadStockByBrand(brandName)
        return
      }
    }

    // 品牌未匹配或未识别 → 如果当前已选品牌，直接在当前库存中过滤
    if (this.data.brandIdx > 0 && this.data.stockList.length > 0) {
      this._applyScanFilter(this.data.stockList)
    } else {
      wx.showToast({ title: brand ? `未找到品牌"${brand}"的库存` : '请先选择品牌', icon: 'none', duration: 2500 })
    }
  },

  // 手动URL输入
  onManualUrlInput(e) {
    this.setData({ manualUrl: e.detail.value, manualUrlError: '' })
  },

  onManualUrlConfirm() {
    const url = (this.data.manualUrl || '').trim()
    if (!url) {
      this.setData({ manualUrlError: '请输入溯源URL地址' })
      return
    }
    if (!url.includes('news.zcckj.com')) {
      this.setData({ manualUrlError: '无效链接：仅支持 news.zcckj.com 域名' })
      return
    }
    this.setData({ showManualUrlModal: false })
    this._invokeParseTireCode(url)
  },

  onManualUrlCancel() {
    this.setData({ showManualUrlModal: false, manualUrl: '', manualUrlError: '' })
    wx.showToast({ title: '已取消', icon: 'none' })
  },
})
