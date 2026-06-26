// 进货登记 — 品牌级联 + 规格选择 + ply/loadIndex 下拉 + 图片上传
const { parseScanCode } = require('../../utils/scanParser')
const { enqueue } = require('../../utils/sync')

// 层级选项
const PLY_OPTIONS = ['无', '4PR','6PR','8PR','10PR','12PR','14PR','16PR','18PR']
// 负荷指数选项（常见值）
const LOAD_INDEX_OPTIONS = ['','82','84','85','86','88','89','91','92','94','95','97','98','100','104','150/147L','152/148M','152/149L']

Page({
  data: {
    // 表单
    formDate: '',
    formSupplierId: '',
    formSupplierName: '',
    formBrandId: '',       // 新增：品牌ID
    formBrand: '朝阳轮胎',     // 品牌名称
    formTireId: '',
    formSize: '',
    formPattern: '',
    formPly: '',
    formLoadIndex: '',     // 新增：负荷指数
    formQty: 1,
    formUnitPrice: '',
    formTotal: '0.00',
    formNote: '',
    formImageList: [],

    // 品牌
    brands: [],
    showBrandPicker: false,

    // 级联规格
    filteredSpecs: [],
    showSpecPicker: false,

    // 层级/负荷下拉
    plyOptions: PLY_OPTIONS,
    plyIndex: 0,
    loadIndexOptions: LOAD_INDEX_OPTIONS,
    loadIndexIdx: 0,

    // 供应商列表
    suppliers: [],
    showSupplierPicker: false,

    // 扫码解析备注
    scanNote: '',
    showScanPhotoModal: false,   // 扫码成功后拍照确认弹窗
    showManualUrlModal: false,   // 手动粘贴URL弹窗
    manualUrl: '',               // 手动输入的URL
    manualUrlError: '',          // URL校验错误信息

    // 新增弹窗
    showAddBrandDialog: false,
    newBrandName: '',
    showAddSupplierDialog: false,
    newSupplierName: '',
    showAddTireDialog: false,
    newTireSize: '',
    newTirePattern: '',
    newTirePly: '',
    newTireLoadIndex: ''
  },

  onLoad() {
    const today = new Date().toISOString().slice(0, 10)
    this.setData({ formDate: today })
  },

  onShow() {
    this._loadBrands()
    this._loadSuppliers()
  },

  // ==================== 品牌 ====================
  _loadBrands() {
    wx.cloud.callFunction({ name: 'manageBrand', data: { action: 'list' } }).then(res => {
      if (res.result && res.result.ok) {
        const brands = res.result.list || []
        this.setData({ brands })
        this._autoSelectDefaultBrand(brands)
      }
    }).catch(err => {
      console.error('manageBrand list 失败:', err)
      // 云函数未部署时直接读库兜底
      wx.cloud.database().collection('brands').orderBy('name', 'asc').get().then(res => {
        const brands = res.data || []
        this.setData({ brands })
        this._autoSelectDefaultBrand(brands)
      }).catch(e => console.error('直接读库也失败:', e))
    })
  },

  // 页面加载时自动匹配默认品牌（formBrand）的 _id 并加载规格
  _autoSelectDefaultBrand(brands) {
    if (this.data.formBrandId) return  // 用户已手动选择，不覆盖
    const defaultBrand = brands.find(b => b.name === this.data.formBrand)
    if (defaultBrand) {
      console.log('_autoSelectDefaultBrand: 匹配到默认品牌', defaultBrand.name, defaultBrand._id)
      this.setData({ formBrandId: defaultBrand._id, formBrand: defaultBrand.name })
      this._loadSpecs(defaultBrand._id)
    } else {
      console.warn('_autoSelectDefaultBrand: 未找到默认品牌', this.data.formBrand)
    }
  },

  showBrandPicker() { this.setData({ showBrandPicker: true }) },
  cancelBrandPicker() { this.setData({ showBrandPicker: false }) },

  selectBrand(e) {
    const item = e.currentTarget.dataset.item
    this.setData({
      formBrandId: item._id,
      formBrand: item.name,
      showBrandPicker: false,
      formTireId: '',         // 切换品牌时清空已选规格
      filteredSpecs: []
    })
    this._loadSpecs(item._id)
  },

  // 按品牌加载规格列表
  _loadSpecs(brandId) {
    if (!brandId) return
    const brand = this.data.formBrand
    console.log('_loadSpecs brandId=', brandId, 'brand=', brand)
    wx.cloud.callFunction({ name: 'getTireSpecs', data: { brandId } }).then(res => {
      console.log('getTireSpecs 返回:', JSON.stringify(res.result))
      if (res.result && res.result.ok) {
        const list = res.result.list || []
        console.log('getTireSpecs brandId 记录数:', list.length)
        // brandId 查不到时，用品牌名称兜底（修复 brandId 空值问题）
        if (list.length === 0 && brand) {
          console.warn('getTireSpecs: brandId 无结果，按品牌名称兜底 brand=', brand)
          wx.cloud.callFunction({ name: 'getTireSpecs', data: { brand } }).then(res2 => {
            if (res2.result && res2.result.ok) {
              const list2 = res2.result.list || []
              console.log('getTireSpecs 品牌名兜底 记录数:', list2.length)
              this.setData({ filteredSpecs: list2 })
            }
          }).catch(e => console.error('getTireSpecs 品牌名兜底异常:', e))
          return
        }
        this.setData({ filteredSpecs: list })
        if (list.length === 0) console.warn('getTireSpecs: 该品牌无规格, brandId=', brandId)
      } else {
        console.error('getTireSpecs 失败:', res.result)
      }
    }).catch(err => {
      console.error('getTireSpecs 调用异常:', err)
      // 云函数未部署时直接读库兜底
      wx.cloud.database().collection('tires').where({ brandId }).orderBy('pattern', 'asc').get().then(res => {
        console.log('直接读库 tires brandId 记录数:', res.data.length)
        const list = res.data || []
        if (list.length === 0 && brand) {
          // 直接读库也按品牌名兜底
          wx.cloud.database().collection('tires').where({ brand }).orderBy('pattern', 'asc').get().then(res2 => {
            console.log('直接读库 tires brand 记录数:', res2.data.length)
            this.setData({ filteredSpecs: res2.data || [] })
          }).catch(e => console.error('直接读库 brand 兜底也失败:', e))
          return
        }
        this.setData({ filteredSpecs: list })
      }).catch(e => console.error('直接读库也失败:', e))
    })
  },

  // ==================== 规格选择器（级联） ====================
  showSpecPicker() {
    if (this.data.filteredSpecs.length === 0) {
      wx.showToast({ title: '请先选择品牌，或手动输入规格', icon: 'none' })
      return
    }
    this.setData({ showSpecPicker: true })
  },
  cancelSpecPicker() { this.setData({ showSpecPicker: false }) },

  selectSpec(e) {
    const item = e.currentTarget.dataset.item
    this.setData({
      formTireId: item._id,
      formSize: item.size,
      formPattern: item.pattern,
      formPly: item.ply || '',
      formLoadIndex: item.loadIndex || '',
      formBrandId: item.brandId || this.data.formBrandId,
      formBrand: item.brand || this.data.formBrand,
      plyIndex: (item.ply ? PLY_OPTIONS.indexOf(item.ply) : 0),
      loadIndexIdx: LOAD_INDEX_OPTIONS.indexOf(item.loadIndex || ''),
      showSpecPicker: false
    })
    this._loadLastPrice(item._id)
  },

  // ==================== 层级/负荷 picker ====================
  onPlyChange(e) {
    const idx = Number(e.detail.value)
    this.setData({ plyIndex: idx, formPly: PLY_OPTIONS[idx] || '' })
  },
  onLoadIndexChange(e) {
    const idx = Number(e.detail.value)
    this.setData({ loadIndexIdx: idx, formLoadIndex: LOAD_INDEX_OPTIONS[idx] || '' })
  },

  // ==================== 品牌新增 ====================
  showAddBrandInput() {
    this.setData({ showAddBrandDialog: true, newBrandName: '' })
  },
  cancelAddBrand() {
    this.setData({ showAddBrandDialog: false, newBrandName: '' })
  },
  onNewBrandInput(e) { this.setData({ newBrandName: e.detail.value }) },
  confirmAddBrand() {
    const name = (this.data.newBrandName || '').trim()
    if (!name) { wx.showToast({ title: '请输入品牌名称', icon: 'none' }); return }
    wx.showLoading({ title: '新增中...' })
    wx.cloud.callFunction({ name: 'manageBrand', data: { action: 'add', data: { name } } }).then(r => {
      wx.hideLoading()
      if (r.result && r.result.ok) {
        wx.showToast({ title: '品牌已添加', icon: 'success' })
        this.setData({ showAddBrandDialog: false, newBrandName: '' })
        this._loadBrands()
      } else {
        wx.showToast({ title: r.result.message || '添加失败', icon: 'none' })
      }
    }).catch(() => { wx.hideLoading(); wx.showToast({ title: '网络异常', icon: 'none' }) })
  },

  // ==================== 供应商 ====================
  _loadSuppliers() {
    const autoSelect = (list) => {
      this.setData({ suppliers: list })
      // 默认选中"朝阳轮胎工厂"
      if (!this.data.formSupplierId || !list.find(s => s._id === this.data.formSupplierId)) {
        const defaultSupplier = list.find(s => s.name === '朝阳轮胎工厂')
        if (defaultSupplier) {
          this.setData({
            formSupplierId: defaultSupplier._id,
            formSupplierName: defaultSupplier.name
          })
        }
      }
    }
    wx.cloud.callFunction({ name: 'manageSupplier', data: { action: 'list' } }).then(res => {
      if (res.result && res.result.ok) {
        autoSelect(res.result.list || [])
      }
    }).catch(err => {
      console.error('manageSupplier list 调用失败:', err)
      // 云函数未部署时直接读库兜底
      wx.cloud.database().collection('suppliers').orderBy('name', 'asc').get().then(res => {
        autoSelect(res.data || [])
      }).catch(e => console.error('直接读库也失败:', e))
    })
  },

  onDateChange(e) { this.setData({ formDate: e.detail.value }) },

  showSupplierPicker() { this.setData({ showSupplierPicker: true }) },
  cancelSupplierPicker() { this.setData({ showSupplierPicker: false }) },

  selectSupplier(e) {
    const item = e.currentTarget.dataset.item
    this.setData({
      formSupplierId: item._id,
      formSupplierName: item.name,
      showSupplierPicker: false
    })
  },

  addSupplier() { this.showAddSupplierInput() },
  showAddSupplierInput() { this.setData({ showAddSupplierDialog: true, newSupplierName: '' }) },
  cancelAddSupplier() { this.setData({ showAddSupplierDialog: false, newSupplierName: '' }) },
  onNewSupplierInput(e) { this.setData({ newSupplierName: e.detail.value }) },
  confirmAddSupplier() {
    const name = (this.data.newSupplierName || '').trim()
    if (!name) { wx.showToast({ title: '请输入供应商名称', icon: 'none' }); return }
    wx.showLoading({ title: '新增中...' })
    wx.cloud.callFunction({ name: 'manageSupplier', data: { action: 'add', data: { name } } }).then(r => {
      wx.hideLoading()
      if (r.result && r.result.ok) {
        wx.showToast({ title: '已添加', icon: 'success' })
        this.setData({ showAddSupplierDialog: false, newSupplierName: '' })
        this._loadSuppliers()
      } else {
        wx.showToast({ title: r.result.message || '添加失败', icon: 'none' })
      }
    }).catch(() => { wx.hideLoading(); wx.showToast({ title: '网络异常', icon: 'none' }) })
  },

  // ==================== 轮胎新增弹窗（含 loadIndex） ====================
  showAddTireInput() {
    this.setData({
      showAddTireDialog: true,
      newTireSize: '', newTirePattern: '', newTirePly: '', newTireLoadIndex: ''
    })
  },
  cancelAddTire() { this.setData({ showAddTireDialog: false }) },
  onNewTireFieldInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [field]: e.detail.value })
  },
  confirmAddTire() {
    const size = (this.data.newTireSize || '').trim()
    const pattern = (this.data.newTirePattern || '').trim()
    if (!size || !pattern) { wx.showToast({ title: '规格和花纹为必填项', icon: 'none' }); return }
    wx.showLoading({ title: '新增中...' })
    wx.cloud.callFunction({
      name: 'addTireSpec',
      data: {
        size, pattern,
        ply: (this.data.newTirePly || '').trim(),
        loadIndex: (this.data.newTireLoadIndex || '').trim(),
        brand: this.data.formBrand || '朝阳轮胎',
        brandId: this.data.formBrandId || ''
      }
    }).then(r => {
      wx.hideLoading()
      console.log('addTireSpec 返回:', JSON.stringify(r.result))
      if (r.result && r.result.ok) {
        const msg = r.result.existed ? '该规格已存在' : '新增成功'
        wx.showToast({ title: msg, icon: 'success' })
        const newPly = this.data.newTirePly || ''
        const newLoad = this.data.newTireLoadIndex || ''
        const update = {
          showAddTireDialog: false,
          formTireId: r.result._id,
          formSize: size, formPattern: pattern,
          formPly: newPly,
          formLoadIndex: newLoad
        }
        // 同步 picker 下标
        if (newPly) {
          const pIdx = PLY_OPTIONS.indexOf(newPly)
          if (pIdx > -1) update.plyIndex = pIdx
        }
        if (newLoad) {
          const lIdx = LOAD_INDEX_OPTIONS.indexOf(newLoad)
          if (lIdx > -1) update.loadIndexIdx = lIdx
        }
        this.setData(update)
        // 新增后立刻刷新当前品牌规格列表
        if (this.data.formBrandId) this._loadSpecs(this.data.formBrandId)
      } else {
        wx.showToast({ title: r.result.message || '新增失败', icon: 'none' })
      }
    }).catch(err => {
      wx.hideLoading()
      console.error('addTireSpec 调用异常:', err)
      wx.showToast({ title: '网络异常', icon: 'none' })
    })
  },

  // ==================== 规格/花纹手动输入（自动匹配） ====================
  onSizePatternInput(e) {
    const field = e.currentTarget.dataset.field
    const val = e.detail.value
    this.setData({ [field]: val })

    const size = field === 'formSize' ? val : this.data.formSize
    const pattern = field === 'formPattern' ? val : this.data.formPattern

    // 规格或花纹被清空 → 清除已匹配的 tireId，防止提交时绕过校验
    if (!size || !pattern) {
      if (this.data.formTireId) {
        this.setData({ formTireId: '' })
      }
      return
    }

    // 两者都有值时尝试自动匹配已有规格
    console.log('onSizePatternInput 调用 getTireSpecs search:', size, pattern)
    wx.cloud.callFunction({
      name: 'getTireSpecs', data: { action: 'search', size, pattern }
    }).then(res => {
      console.log('getTireSpecs search 返回:', JSON.stringify(res.result))
      if (res.result && res.result.ok && res.result.tire) {
        const t = res.result.tire
        this.setData({
          formTireId: t._id,
          formPly: t.ply || this.data.formPly,
          formLoadIndex: t.loadIndex || this.data.formLoadIndex,
          formBrand: t.brand || this.data.formBrand,
          formBrandId: t.brandId || this.data.formBrandId,
          plyIndex: t.ply ? PLY_OPTIONS.indexOf(t.ply) : 0,
          loadIndexIdx: LOAD_INDEX_OPTIONS.indexOf(t.loadIndex || '')
        })
        this._loadLastPrice(t._id)
      } else {
        this.setData({ formTireId: '' })
      }
    }).catch(err => { console.error('getTireSpecs search 异常:', err) })
  },

  _loadLastPrice(tireId) {
    wx.cloud.callFunction({ name: 'getTireProfile', data: { tireId } }).then(res => {
      if (res.result && res.result.ok && res.result.lastPrice) {
        this.setData({ formUnitPrice: String(res.result.lastPrice) })
        this._calcTotal()
      }
    }).catch(() => {})
  },

  // ==================== 表单计算 ====================
  onFieldInput(e) {
    const field = e.currentTarget.dataset.field
    const val = e.detail.value
    this.setData({ [field]: val }, () => {
      if (field === 'formQty' || field === 'formUnitPrice') this._calcTotal()
    })
  },
  _calcTotal() {
    const qty = Number(this.data.formQty) || 0
    const price = Number(this.data.formUnitPrice) || 0
    this.setData({ formTotal: (qty * price).toFixed(2) })
  },

  // ==================== 扫码入库（增强扫码 + 云函数解析 + 手动URL兜底） ====================
  scanCode() {
    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['qrCode'],
      autoZoom: true,           // 自动缩放，解决远景/小码识别
      barCodeEnhance: true,     // 条形码增强（部分设备支持）
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

  // 手动URL输入
  onManualUrlInput(e) {
    this.setData({ manualUrl: e.detail.value, manualUrlError: '' })
  },

  // 手动URL确认：校验域名 → 调用云函数解析
  onManualUrlConfirm() {
    const url = (this.data.manualUrl || '').trim()
    if (!url) {
      this.setData({ manualUrlError: '请输入溯源URL地址' })
      return
    }
    // 必须包含 news.zcckj.com
    if (!url.includes('news.zcckj.com')) {
      this.setData({ manualUrlError: '无效链接：仅支持 news.zcckj.com 域名' })
      return
    }
    this.setData({ showManualUrlModal: false })
    this._invokeParseTireCode(url)
  },

  // 手动URL取消
  onManualUrlCancel() {
    this.setData({ showManualUrlModal: false, manualUrl: '', manualUrlError: '' })
    wx.showToast({ title: '已取消', icon: 'none' })
  },

  // 统一解析入口：直接调用 parseTireCode 云函数（API逆向 + 策略1-4兜底）
  _invokeParseTireCode(code) {
    wx.showLoading({ title: '解析中...', mask: true })

    wx.cloud.callFunction({ name: 'parseTireCode', data: { url: code } }).then(cfRes => {
      wx.hideLoading()
      const result = cfRes.result
      if (result && result.code === 0 && result.data) {
        this._autoFillFromParse(result.data)
        wx.showToast({ title: '扫码识别成功', icon: 'success' })
        this.setData({ showScanPhotoModal: true })
      } else {
        const msg = (result && result.msg) || '无法识别轮胎信息，请手动输入'
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
      const ply = parsed.ply || ''
      const update = {
        formSize: parsed.size || '',
        formPattern: parsed.pattern || '',
        formPly: ply,
        formBrand: parsed.brand || this.data.formBrand,
        formUnitPrice: parsed.price || '',
        formNote: parsed.note || '',
        scanNote: '本地解析，请核对信息'
      }
      if (ply) {
        const pIdx = PLY_OPTIONS.indexOf(ply)
        if (pIdx > -1) update.plyIndex = pIdx
      }
      this.setData(update)
      wx.showToast({ title: '本地识别成功，请核对', icon: 'success' })
      this.setData({ showScanPhotoModal: true })
      if (parsed.size && parsed.pattern) {
        this.onSizePatternInput({ detail: { value: parsed.pattern }, currentTarget: { dataset: { field: 'formPattern' } } })
      }
    } else {
      wx.showToast({ title: '无法识别，请手动输入', icon: 'none', duration: 2500 })
    }
  },

  _autoFillFromParse(data) {
    const size = data.size || data.spec || ''
    const pattern = data.pattern || ''
    const ply = data.ply || ''
    const loadSpeed = data.loadSpeed || data.loadIndex || ''
    const brand = data.brand || this.data.formBrand
    const price = data.price !== undefined ? Number(data.price) : 0
    const serialNo = data.serialNo || ''

    let scanNote = '扫码识别成功，请核对信息'
    if (serialNo) scanNote += ' | 序列号: ' + serialNo

    const updates = {
      formSize: size,
      formPattern: pattern,
      formPly: ply,
      formLoadIndex: loadSpeed,
      scanNote
    }

    // 有价格→填入单价+重算总价
    if (price > 0) {
      updates.formUnitPrice = String(price)
    }

    // ply/loadIndex 同步到 picker 下标
    if (ply) {
      const plyIdx = ply ? PLY_OPTIONS.indexOf(ply) : 0
      if (plyIdx > -1) updates.plyIndex = plyIdx
    }
    if (loadSpeed) {
      const loadIdx = LOAD_INDEX_OPTIONS.indexOf(loadSpeed)
      if (loadIdx > -1) updates.loadIndexIdx = loadIdx
    }

    // 品牌匹配：在已加载的 brands 列表中查找
    if (brand) {
      const matched = this.data.brands.find(b =>
        b.name === brand ||
        b.name.includes(brand) ||
        brand.includes(b.name)
      )
      if (matched) {
        updates.formBrandId = matched._id
        updates.formBrand = matched.name
      } else {
        // 未匹配到的品牌也填入，提交时自动创建
        updates.formBrand = brand
        updates.formBrandId = ''
      }
    }

    this.setData(updates)
    if (price > 0) this._calcTotal()

    // 匹配到品牌后加载该品牌规格列表
    if (updates.formBrandId) {
      this._loadSpecs(updates.formBrandId)
    }

    // 尝试通过 getTireSpecs 搜索已有规格自动匹配 tireId + 历史进价
    if (size && pattern) {
      wx.cloud.callFunction({
        name: 'getTireSpecs',
        data: { action: 'search', size, pattern }
      }).then(res => {
        if (res.result && res.result.ok && res.result.tire) {
          const t = res.result.tire
          const update = {
            formTireId: t._id,
            formPly: t.ply || this.data.formPly,
            formLoadIndex: t.loadIndex || this.data.formLoadIndex,
            formBrand: t.brand || this.data.formBrand,
            formBrandId: t.brandId || this.data.formBrandId
          }
          // 同步 picker 下标
          if (t.ply) {
            const pIdx = PLY_OPTIONS.indexOf(t.ply)
            if (pIdx > -1) update.plyIndex = pIdx
          }
          if (t.loadIndex) {
            const lIdx = LOAD_INDEX_OPTIONS.indexOf(t.loadIndex)
            if (lIdx > -1) update.loadIndexIdx = lIdx
          }
          this.setData(update)
          // 自动回填历史进价
          this._loadLastPrice(t._id)
        }
      }).catch(() => {})
    }
  },

  // 扫码成功后拍照
  onSkipPhoto() {
    this.setData({ showScanPhotoModal: false })
  },
  _takePhotoAfterScan() {
    this.setData({ showScanPhotoModal: false })
    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['camera'],
      success: res => {
        wx.showLoading({ title: '上传照片...', mask: true })
        this._compressAndUpload(res.tempFilePaths[0]).then(fileID => {
          wx.hideLoading()
          if (fileID) {
            // 扫码照片排到最前面
            this.setData({ formImageList: [fileID, ...this.data.formImageList] })
            wx.showToast({ title: '照片已保存', icon: 'success' })
          }
        })
      },
      fail: () => {
        // 用户取消拍照不提示错误
      }
    })
  },

  // ==================== 图片上传 ====================
  chooseImage() {
    const remain = 6 - this.data.formImageList.length
    if (remain <= 0) { wx.showToast({ title: '最多上传6张', icon: 'none' }); return }
    wx.chooseImage({ count: remain, sizeType: ['compressed'], success: res => {
      wx.showLoading({ title: '压缩上传中...' })
      const tasks = res.tempFilePaths.map(path => this._compressAndUpload(path))
      Promise.all(tasks).then(results => {
        wx.hideLoading()
        this.setData({ formImageList: [...this.data.formImageList, ...results.filter(Boolean)] })
      })
    }})
  },
  _compressAndUpload(tempPath) {
    return new Promise(resolve => {
      wx.compressImage({
        src: tempPath, compressedWidth: 1080,
        success: compressed => {
          if (!wx.cloud) { resolve(tempPath); return }
          wx.cloud.uploadFile({
            cloudPath: `tires/${Date.now()}_${Math.random().toString(36).slice(2,6)}.jpg`,
            filePath: compressed.tempFilePath || tempPath,
            success: upRes => resolve(upRes.fileID),
            fail: () => resolve(tempPath)
          })
        },
        fail: () => resolve(tempPath)
      })
    })
  },
  removeImage(e) {
    const list = [...this.data.formImageList]
    list.splice(e.currentTarget.dataset.idx, 1)
    this.setData({ formImageList: list })
  },

  // ==================== 提交（含自动补建） ====================
  submit() {
    if (this.data.submitting) return
    const { formSupplierId, formTireId, formQty, formUnitPrice, formDate, formSize, formPattern, formBrand, formBrandId, formPly, formLoadIndex } = this.data

    // 收集所有校验错误（按页面从上到下的顺序）
    const errors = []

    // 1. 供应商
    if (!formSupplierId) {
      errors.push({ msg: '请选择供应商', field: 'field-supplier' })
    }

    // 2. 规格与花纹：要么已有 tireId，要么两者都填用于自动创建
    if (!formTireId) {
      if (!formSize || !formSize.trim()) {
        errors.push({ msg: '请填写轮胎规格（如 205/55R16）', field: 'field-spec' })
      }
      if (!formPattern || !formPattern.trim()) {
        errors.push({ msg: '请填写花纹型号（如 SA37）', field: 'field-pattern' })
      }
    } else {
      // 有 tireId 但规格/花纹被手动清空的情况（兜底校验）
      if (!formSize || !formSize.trim()) {
        errors.push({ msg: '轮胎规格不能为空', field: 'field-spec' })
      }
      if (!formPattern || !formPattern.trim()) {
        errors.push({ msg: '花纹型号不能为空', field: 'field-pattern' })
      }
    }

    // 3. 单价
    if (!formUnitPrice || Number(formUnitPrice) <= 0) {
      errors.push({ msg: '请输入有效单价', field: 'field-unitprice' })
    }

    // 4. 数量
    if (!formQty || Number(formQty) <= 0) {
      errors.push({ msg: '请输入有效数量', field: 'field-qty' })
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

    // 有规格+花纹但无 tireId → 自动补建
    if (!formTireId && formSize && formPattern) {
      this._autoCreateTireAndSubmit()
      return
    }
    this._doSubmit(formTireId)
  },

  _autoCreateTireAndSubmit() {
    wx.showLoading({ title: '自动创建轮胎品类...' })
    wx.cloud.callFunction({
      name: 'addTireSpec',
      data: {
        size: this.data.formSize,
        pattern: this.data.formPattern,
        ply: this.data.formPly === '无' ? '' : (this.data.formPly || ''),
        loadIndex: this.data.formLoadIndex || '',
        brand: this.data.formBrand || '朝阳轮胎',
        brandId: this.data.formBrandId || ''
      }
    }).then(r => {
      wx.hideLoading()
      console.log('addTireSpec (自动创建) 返回:', JSON.stringify(r.result))
      if (r.result && r.result.ok) {
        const tireId = r.result._id
        this.setData({ formTireId: tireId })
        this._doSubmit(tireId)
      } else {
        wx.showToast({ title: r.result.message || '轮胎创建失败', icon: 'none' })
      }
    }).catch(err => {
      wx.hideLoading()
      console.error('addTireSpec (自动创建) 异常:', err)
      wx.showToast({ title: '轮胎创建失败，请重试', icon: 'none' })
    })
  },

  _doSubmit(tireId) {
    const { formSupplierId, formQty, formUnitPrice, formDate } = this.data
    const data = {
      supplierId: formSupplierId, tireId,
      qty: Number(formQty), unitPrice: Number(formUnitPrice),
      date: formDate, note: this.data.formNote, imageList: this.data.formImageList
    }
    wx.showLoading({ title: '提交中...' })
    wx.cloud.callFunction({ name: 'addPurchase', data }).then(res => {
      wx.hideLoading()
      if (res.result && res.result.ok) {
        wx.showToast({ title: '进货登记成功', icon: 'success' })
        this._resetForm()
      } else {
        enqueue({ fn: 'addPurchase', data })
        wx.showToast({ title: '已离线保存，网络恢复后自动同步', icon: 'none' })
      }
    }).catch(() => {
      wx.hideLoading()
      enqueue({ fn: 'addPurchase', data })
      wx.showToast({ title: '已离线保存', icon: 'none' })
    })
  },

  _resetForm() {
    this.setData({
      formSupplierId: '', formSupplierName: '',
      formBrandId: '', formTireId: '',
      formSize: '', formPattern: '', formPly: '', formLoadIndex: '',
      formQty: 1, formUnitPrice: '', formTotal: '0.00',
      formNote: '', formImageList: [], scanNote: '', showScanPhotoModal: false,
      filteredSpecs: [], plyIndex: 0, loadIndexIdx: 0
    })
  }
})
