const { GAME_META, GAME_TYPES, getPagePath } = require('../../utils/util')

Page({
  data: {
    loading: false,
    myOpenId: '',
    myNickName: '',
    myAvatarUrl: '',
    // 游戏分类
    showGameList: false,
    gameList: [],
    // 加入房间
    showJoinInput: false,
    joinRoomId: '',

    // ===== 留言板 =====
    showMessageBoard: false,
    messages: [],
    newMessageText: ''
  },

  onLoad() {
    wx.showShareMenu({ withShareTicket: true, menus: ['shareAppMessage', 'shareTimeline'] })
    this._buildGameList()
    this._syncIdentity()
  },

  onShareAppMessage() {
    return {
      title: `${this.data.myNickName} 邀你来计分！`,
      path: '/pages/index/index',
      imageUrl: ''
    }
  },

  onShow() {
    this._syncIdentity()
  },

  // 同步用户身份（不阻塞 UI，异步填充）
  _syncIdentity() {
    const app = getApp()
    const cache = wx.getStorageSync('__my_identity__') || {}
    if (app.globalData.openId && app.globalData.openId !== this.data.myOpenId) {
      this.setData({
        myOpenId: app.globalData.openId,
        myNickName: app.globalData.nickName || cache.nickName || '',
        myAvatarUrl: cache.avatarUrl || ''
      })
    } else if (!this.data.myNickName && cache.nickName) {
      this.setData({
        myNickName: cache.nickName,
        myAvatarUrl: cache.avatarUrl || ''
      })
    }
  },

  _buildGameList() {
    const list = []
    for (const [type, meta] of Object.entries(GAME_META)) {
      list.push({ type, ...meta })
    }
    this.setData({ gameList: list })
  },

  // ---- 双入口导航 ----
  openScoring() {
    this.setData({ showGameList: true })
  },

  openTireInventory() {
    wx.navigateTo({ url: '/pages/tire_dashboard/tire_dashboard' })
  },

  backToHome() {
    this.setData({ showGameList: false })
  },

  // ---- 进入计分页面（不自动创建房间，先展示首页/记录/我的主界面） ----
  onCreateRoom(e) {
    const gameType = e.currentTarget.dataset.type
    if (!gameType) return
    wx.navigateTo({ url: getPagePath(gameType) })
  },

  // ---- 加入房间 ----
  showJoinInput() { this.setData({ showJoinInput: true, joinRoomId: '' }) },
  cancelJoin() { this.setData({ showJoinInput: false, joinRoomId: '' }) },
  _preventBubble() {},

  setJoinRoomId(e) {
    const val = (e.detail.value || '').replace(/\D/g, '').slice(0, 6)
    this.setData({ joinRoomId: val })
  },

  joinRoom() {
    const code = this.data.joinRoomId
    if (!code) { wx.showToast({ title: '请输入房间号', icon: 'none' }); return }
    if (code.length !== 6) { wx.showToast({ title: '房间号应为6位数字', icon: 'none' }); return }

    if (!this.data.myNickName) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' })
      return
    }

    this.setData({ showJoinInput: false, joinRoomId: '' })
    wx.showLoading({ title: '加入中...', mask: true })

    // 调用 joinRoom 云函数（与 walk_scoring / mahjong_scoring 内部一致）
    // 云函数根据 _id = roomCode 查找房间，自动识别 gameType 并返回
    wx.cloud.callFunction({
      name: 'joinRoom',
      data: {
        roomCode: code,
        nickName: this.data.myNickName,
        avatarUrl: this.data.myAvatarUrl
      }
    }).then(res => {
      wx.hideLoading()
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message, icon: 'none' })
        return
      }
      // 云函数返回 room.gameType，根据类型跳转对应页面
      const gameType = res.result.room && res.result.room.gameType
      const path = getPagePath(gameType)
      // 统一用 roomCode 参数（walk_scoring 和 mahjong_scoring 都认 query.roomCode）
      wx.navigateTo({ url: `${path}?roomCode=${code}` })
    }).catch(err => {
      wx.hideLoading()
      wx.showToast({ title: '加入失败: ' + (err.errMsg || '网络错误'), icon: 'none' })
    })
  },

  // ---- 头像 + 昵称 ----
  onChooseAvatar(e) {
    const tempUrl = e.detail.avatarUrl
    if (!tempUrl) return
    // 先用临时 URL 展示头像（仅当前会话有效），同步到 globalData
    this.setData({ myAvatarUrl: tempUrl })
    getApp().globalData.avatarUrl = tempUrl
    // 上传到云存储，成功后持久化 cloud:// fileID
    if (wx.cloud) {
      const openId = this.data.myOpenId || getApp().globalData.openId || 'unknown'
      wx.cloud.uploadFile({
        cloudPath: `avatars/${openId}_${Date.now()}.png`,
        filePath: tempUrl,
        success: res => {
          const url = res.fileID
          // 仅在上传成功后写入 localStorage，防止临时 URL 泄漏到持久化缓存
          const ident = wx.getStorageSync('__my_identity__') || {}
          ident.avatarUrl = url
          wx.setStorageSync('__my_identity__', ident)
          getApp().globalData.avatarUrl = url
          this.setData({ myAvatarUrl: url })
        },
        fail: err => {
          console.error('头像上传失败:', err.errMsg || err)
          // 上传失败时回退显示，不清空 globalData（保留临时 URL 供当前会话使用）
          wx.showToast({ title: '头像保存失败，请重试', icon: 'none' })
        }
      })
    } else {
      // 无云环境兜底：虽然临时 URL 下次启动会失效，但至少当前会话可用
      const id = wx.getStorageSync('__my_identity__') || {}
      id.avatarUrl = tempUrl
      wx.setStorageSync('__my_identity__', id)
    }
  },

  onNickNameBlur(e) {
    const name = (e.detail.value || '').trim()
    if (name && name !== this.data.myNickName) {
      getApp().setNickName(name)
      this.setData({ myNickName: name })
    }
  },

  // nickname 输入框确认事件（type="nickname" 键盘上的确认键/微信昵称选择器）
  onNickNameConfirm(e) {
    const name = (e.detail.value || '').trim()
    if (name && name !== this.data.myNickName) {
      getApp().setNickName(name)
      this.setData({ myNickName: name })
    }
  },

  // ================================================================
  // 留言板 + 建议反馈
  // ================================================================

  onOpenMessageBoard() {
    this.setData({ showMessageBoard: true })
    this._loadMessages()
  },

  onCloseMessageBoard() {
    this.setData({ showMessageBoard: false })
  },

  /** 手动刷新留言板（从云端重新拉取） */
  onRefreshMessages() {
    wx.showLoading({ title: '刷新中...' })
    this._loadMessages(function () {
      wx.hideLoading()
    })
  },

  onMessageInput(e) {
    this.setData({ newMessageText: e.detail.value || '' })
  },

  onSendMessage() {
    const content = (this.data.newMessageText || '').trim()
    if (!content) { wx.showToast({ title: '请输入留言内容', icon: 'none' }); return }
    if (content.length > 500) { wx.showToast({ title: '留言不能超过500字', icon: 'none' }); return }
    const nickName = this.data.myNickName || '匿名用户'
    const avatarUrl = this.data.myAvatarUrl || ''
    const localId = 'm_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    const msg = {
      id: localId,
      nickName,
      avatarUrl,
      content,
      timeStr: this._formatMsgTime(new Date()),
      timeFull: this._formatMsgFull(new Date())
    }

    const messages = [msg, ...this.data.messages]
    this.setData({ messages, newMessageText: '' })
    this._saveMessages(messages)
    wx.showToast({ title: '留言成功', icon: 'success' })

    // 异步同步到云端 messageBoard 云函数（不阻塞 UI）
    if (wx.cloud) {
      wx.cloud.callFunction({
        name: 'messageBoard',
        data: { action: 'add', localId, nickName, avatarUrl, content }
      }).catch(function (err) {
        console.error('[留言板] 云端发送失败:', err.errMsg || err)
      })
    }
  },

  onDeleteMessage(e) {
    var id = e.currentTarget.dataset.id
    var self = this
    var msg = this.data.messages.find(function (m) { return m.id === id })
    if (msg && msg.nickName !== this.data.myNickName) {
      wx.showToast({ title: '只能删除自己的留言', icon: 'none' })
      return
    }
    wx.showModal({
      title: '删除留言',
      content: '确定要删除这条留言吗？',
      success: function (res) {
        if (!res.confirm) return
        var messages = self.data.messages.filter(function (m) { return m.id !== id })
        self.setData({ messages: messages })
        self._saveMessages(messages)
        // 异步删除云端记录
        if (wx.cloud) {
          wx.cloud.callFunction({
            name: 'messageBoard',
            data: { action: 'delete', localId: id }
          }).catch(function (err) {
            console.error('[留言板] 云端删除失败:', err.errMsg || err)
          })
        }
        wx.showToast({ title: '已删除', icon: 'success' })
      }
    })
  },

  _loadMessages(callback) {
    var local = wx.getStorageSync('__app_messages__') || []
    if (local.length > 0) {
      this.setData({ messages: local })
    }
    // 从云端拉取（通过云函数，避免客户端权限/索引问题）
    if (wx.cloud) {
      var self = this
      wx.cloud.callFunction({
        name: 'messageBoard',
        data: { action: 'list' }
      }).then(function (res) {
        console.log('[留言板] 云端返回:', JSON.stringify({ ok: res.result && res.result.ok, count: res.result && res.result.messages ? res.result.messages.length : 0, message: res.result && res.result.message }))
        if (res.result && res.result.ok && res.result.messages) {
          var cloudMsgs = res.result.messages.map(function (item) {
            return {
              id: item.localId || item.cloudId,   // 优先用 localId，确保与本地去重
              nickName: item.nickName || '匿名用户',
              avatarUrl: item.avatarUrl || '',
              content: item.content || '',
              timeStr: self._formatMsgTime(new Date(item.createTime)),
              timeFull: self._formatMsgFull(new Date(item.createTime))
            }
          })
          // 诊断：打印云端前3条留言的昵称和 ID
          console.log('[留言板] 云端前3条:', cloudMsgs.slice(0, 3).map(function (m) { return { nick: m.nickName, id: m.id } }))
          var existingIds = new Set(self.data.messages.map(function (m) { return m.id }))
          console.log('[留言板] 本地已有ID:', Array.from(existingIds).slice(0, 5))
          var newMsgs = cloudMsgs.filter(function (m) { return !existingIds.has(m.id) })
          console.log('[留言板] 新增条数:', newMsgs.length)
          if (newMsgs.length > 0) {
            var merged = newMsgs.concat(self.data.messages)
            self.setData({ messages: merged })
            self._saveMessages(merged)
          } else {
            console.log('[留言板] 无新消息（已有' + self.data.messages.length + '条本地消息）')
          }
        } else {
          console.warn('[留言板] 云端返回异常:', JSON.stringify(res.result))
        }
        if (callback) callback()
      }).catch(function (err) {
        console.error('[留言板] 云端拉取失败:', err.errMsg || err)
        if (callback) callback()
      })
    } else {
      if (callback) callback()
    }
  },

  /** 保存留言到本地存储（云端同步已由各发送入口通过 messageBoard 云函数完成） */
  _saveMessages(messages) {
    var clipped = messages.slice(0, 200)
    wx.setStorageSync('__app_messages__', clipped)
  },

  _formatMsgTime(date) {
    const now = new Date()
    const diff = now - date
    if (diff < 60 * 1000) return '刚刚'
    if (diff < 60 * 60 * 1000) return Math.floor(diff / (60 * 1000)) + '分钟前'
    if (diff < 24 * 60 * 60 * 1000) return Math.floor(diff / (60 * 60 * 1000)) + '小时前'
    if (diff < 7 * 24 * 60 * 60 * 1000) return Math.floor(diff / (24 * 60 * 60 * 1000)) + '天前'
    return (date.getMonth() + 1) + '/' + date.getDate()
  },

  _formatMsgFull(date) {
    const pad = n => n < 10 ? '0' + n : n
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  }
})
