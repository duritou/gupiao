// 分段车牌虚拟键盘自定义组件 v2
// 8 格位框 + 省份横向滑动 + 虚拟按键/原生键盘双模式 + 新能源位标记
Component({
  properties: {
    value: {
      type: String,
      value: '',
      observer(newVal) {
        if (newVal !== this._buildPlateString()) {
          this._syncFromValue(newVal)
        }
      }
    },
    placeholder: {
      type: String,
      value: '点击输入车牌号'
    },
    disabled: {
      type: Boolean,
      value: false
    }
  },

  data: {
    // 8 个位框: [0]省份 [1]-[6]字母数字 [7]新能源位
    slots: ['', '', '', '', '', '', '', ''],
    cursorIndex: 0,          // 当前光标所在格 (0-7)
    showKeyboard: false,     // 是否展开键盘区
    inputMode: 'virtual',    // 'virtual' | 'native'（双模式）
    nativeValue: '',         // 原生键盘临时值
    plateType: '',           // 'fuel' | 'newEnergy' | ''
    plateComplete: false,    // 前 7 位是否填满

    // 省份列表（31 个大陆省份简称）
    provinces: [
      '京','津','沪','渝','冀','豫','云','辽','黑',
      '湘','皖','鲁','新','苏','浙','赣','鄂','桂',
      '甘','晋','蒙','陕','吉','闽','贵','粤','青',
      '藏','川','宁','琼'
    ],

    // 数字行
    digitKeys: ['1','2','3','4','5','6','7','8','9','0'],

    // 字母行（已过滤 I、O）
    letterRow1: ['Q','W','E','R','T','Y','U','P','A','S'],
    letterRow2: ['D','F','G','H','J','K','L','Z','X','C'],
    letterRow3: ['V','B','N','M']
  },

  lifetimes: {
    attached() {
      this._syncFromValue(this.properties.value || '')
    }
  },

  methods: {
    // ========== 外部 value ↔ 内部 slots 双向同步 ==========

    _syncFromValue(val) {
      val = (val || '').trim().toUpperCase().replace(/[IO]/g, '') // 过滤 I/O
      const slots = ['', '', '', '', '', '', '', '']
      for (let i = 0; i < Math.min(val.length, 8); i++) {
        slots[i] = val.charAt(i)
      }
      const filledCount = slots.slice(1, 7).filter(Boolean).length
      const plateComplete = !!slots[0] && filledCount === 6
      const plateType = slots[7] ? 'newEnergy' : (plateComplete ? 'fuel' : '')
      this.setData({ slots, plateType, plateComplete })
    },

    _buildPlateString() {
      return this.data.slots.join('')
    },

    _emitChange() {
      const plate = this._buildPlateString()
      this.triggerEvent('input', { value: plate, plateType: this.data.plateType })
      if (this.data.plateComplete) {
        this.triggerEvent('complete', { value: plate, plateType: this.data.plateType })
      }
    },

    // ========== 展开/收起键盘 ==========

    onToggleKeyboard() {
      if (this.properties.disabled) return
      const show = !this.data.showKeyboard
      this.setData({
        showKeyboard: show,
        inputMode: 'virtual',
        nativeValue: ''
      })
      if (show) {
        // 默认光标到第一个空格
        const firstEmpty = this.data.slots.findIndex(s => !s)
        this.setData({ cursorIndex: firstEmpty >= 0 ? firstEmpty : 0 })
        this.triggerEvent('focus')
      } else {
        this.triggerEvent('blur')
      }
    },

    onCloseKeyboard() {
      this.setData({ showKeyboard: false, inputMode: 'virtual', nativeValue: '' })
      this.triggerEvent('blur')
    },

    // ========== 光标定位：点击任意位框 ==========

    onSlotTap(e) {
      if (this.properties.disabled) return
      const idx = Number(e.currentTarget.dataset.index)
      this.setData({
        cursorIndex: idx,
        showKeyboard: true,
        inputMode: 'virtual',
        nativeValue: ''
      })
    },

    // ========== 省份选择（横向滑动条点击） ==========

    onProvinceTap(e) {
      if (this.properties.disabled) return
      const prov = e.currentTarget.dataset.prov
      const slots = this.data.slots.slice()
      slots[0] = prov
      // 省份填入后光标自动跳到第 2 格
      const cursorIndex = 1
      this.setData({ slots, cursorIndex, showKeyboard: true, nativeValue: '' }, () => {
        this._updatePlateState()
        this._emitChange()
      })
    },

    // ========== 虚拟按键输入 ==========

    onKeyTap(e) {
      if (this.properties.disabled) return
      const char = e.currentTarget.dataset.key
      const idx = this.data.cursorIndex

      // 省份位（idx=0）通过省份选择器输入，虚拟按键仅操作 idx 1-7
      if (idx === 0) {
        wx.showToast({ title: '请在上方滑动选择省份', icon: 'none', duration: 1500 })
        return
      }
      if (idx >= 8) return

      const slots = this.data.slots.slice()
      slots[idx] = char
      // 光标前进到下一格（跳过已填的格子）
      let next = idx + 1
      while (next < 8 && slots[next]) next = next + 1
      if (next >= 8) next = 7 // 停在最后一格

      this.setData({ slots, cursorIndex: next }, () => {
        this._updatePlateState()
        this._emitChange()
      })
    },

    // ========== 退格 ==========

    onBackspace() {
      if (this.properties.disabled) return
      const idx = this.data.cursorIndex
      const slots = this.data.slots.slice()

      if (slots[idx]) {
        // 当前格有字符 → 清空当前格
        slots[idx] = ''
        this.setData({ slots }, () => {
          this._updatePlateState()
          this._emitChange()
        })
      } else if (idx > 0) {
        // 当前格为空 → 光标左移并清空前一格
        const prev = idx - 1
        slots[prev] = ''
        this.setData({ slots, cursorIndex: prev }, () => {
          this._updatePlateState()
          this._emitChange()
        })
      }
    },

    // ========== 清空全部 ==========

    onClear() {
      if (this.properties.disabled) return
      const empty = ['', '', '', '', '', '', '', '']
      this.setData({
        slots: empty,
        cursorIndex: 0,
        showKeyboard: false,
        plateType: '',
        plateComplete: false,
        nativeValue: ''
      })
      this.triggerEvent('input', { value: '', plateType: '' })
      this.triggerEvent('clear')
    },

    // ========== 确认完成 ==========

    onConfirm() {
      const plate = this._buildPlateString()
      const hasProvince = !!this.data.slots[0]
      const regularLen = this.data.slots.slice(1, 7).filter(Boolean).length

      if (!hasProvince) {
        wx.showToast({ title: '请选择省份简称', icon: 'none' })
        return
      }
      if (regularLen < 5) {
        wx.showToast({ title: '车牌号至少 6 位', icon: 'none' })
        return
      }

      this.setData({ showKeyboard: false })
      this.triggerEvent('complete', { value: plate, plateType: this.data.plateType })
    },

    // ========== 切换原生键盘模式 ==========

    onToggleNativeMode() {
      if (this.properties.disabled) return
      const toNative = this.data.inputMode !== 'native'
      if (toNative) {
        const current = this._buildPlateString()
        this.setData({ inputMode: 'native', nativeValue: current })
        // 延迟聚焦避免与按钮态冲突
        setTimeout(() => {
          this.setData({ _nativeFocus: true })
        }, 150)
      } else {
        this.setData({ inputMode: 'virtual', nativeValue: '' })
      }
    },

    // 原生键盘输入事件
    onNativeInput(e) {
      let raw = (e.detail.value || '').toUpperCase()
      // 过滤 I、O
      raw = raw.replace(/[IO]/g, '')
      // 限制最多 8 位
      if (raw.length > 8) raw = raw.slice(0, 8)

      // 验证首位是否为合法省份（或等待用户继续输入）
      const slots = ['', '', '', '', '', '', '', '']
      for (let i = 0; i < Math.min(raw.length, 8); i++) {
        slots[i] = raw.charAt(i)
      }

      this.setData({ slots, nativeValue: raw }, () => {
        this._updatePlateState()
        this._emitChange()
      })
    },

    // 原生键盘确认
    onNativeConfirm() {
      this.setData({ showKeyboard: false, inputMode: 'virtual' })
      const plate = this._buildPlateString()
      this.triggerEvent('complete', { value: plate, plateType: this.data.plateType })
    },

    // ========== 内部状态更新 ==========

    _updatePlateState() {
      const slots = this.data.slots
      const hasProvince = !!slots[0]
      const regularFilled = slots.slice(1, 7).filter(Boolean).length
      const plateComplete = hasProvince && regularFilled === 6
      const plateType = slots[7] ? 'newEnergy' : (plateComplete ? 'fuel' : '')
      this.setData({ plateType, plateComplete })
    }
  }
})
