// 打牌计分 — 线下计分器
const { GAME_TYPES, IDENTITY_POLL_MAX, IDENTITY_POLL_INTERVAL } = require('../../utils/util')

const STORAGE_WALK_ROOM = '__walk_room__'

const nowDateTimeStr = () => {
  const d = new Date()
  const pad = n => n < 10 ? '0' + n : n
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

Page({
  data: {
    loading: true,
    // 用户身份
    myOpenId: '',
    myNickName: '',
    myAvatarUrl: '',
    // 房间
    roomId: '',
    roomCode: '',
    isCreator: false,
    // 数据
    players: [],
    poolScore: 0,
    records: [],
    verify: true,
    // 公共池取分（谁点谁取）
    lastTakePlayer: null,    // 最近一次取分的玩家 { openId, avatarUrl, nickName }
    // 平分锁定状态（服务端原子锁，getRoomInfo 返回）
    fractionMode: '',        // '' | 'half' | 'third'
    fractionAmount: 0,       // 锁定后每人固定可取分数
    fractionTakenBy: [],     // 已取分玩家 openId 列表
    // 转账弹窗（点击玩家头像 → 转分给该玩家）
    showTransfer: false,
    transferTargetOpenId: '',
    transferTargetName: '',
    transferTargetAvatar: '',
    transferAmount: '',
    // UI
    showJoinInput: false,
    joinRoomCode: '',
    // 自定义上分弹窗（点击头像）
    showCustomUpDialog: false,
    customUpAmount: '',
    // 自定义取分弹窗
    showCustomTakeDialog: false,
    customTakeAmount: '',
    showSettleDialog: false,
    acting: false,
    _pendingSyncs: 0,  // 后台同步计数器，watcher 在同步期间跳过重载
    // 流水记录筛选
    recordFilterOpenId: ''  // 空字符串 = 显示全部，否则只显示该 openId 的流水
  },

  onLoad(query) {
    wx.showShareMenu({ withShareTicket: true, menus: ['shareAppMessage', 'shareTimeline'] })
    // 安全兜底：6 秒后强制结束 loading，防止卡死
    this._loadingTimer = setTimeout(() => {
      if (this.data.loading) {
        console.warn('[walk] 加载超时')
        this.setData({ loading: false })
      }
    }, 6000)
    this._waitReady(query)
  },

  onShow() {
    // 从 storage 同步最新的身份信息（支持跨页面头像/昵称互通）
    const cache = wx.getStorageSync('__my_identity__') || {}
    const updates = {}
    if (cache.nickName && cache.nickName !== this.data.myNickName) {
      updates.myNickName = cache.nickName
    }
    if (cache.avatarUrl && cache.avatarUrl !== this.data.myAvatarUrl) {
      updates.myAvatarUrl = cache.avatarUrl
    }
    if (Object.keys(updates).length > 0) {
      this.setData(updates)
    }
  },

  onShareAppMessage() {
    return {
      title: `${this.data.myNickName} 邀你加入打牌计分`,
      path: `/pages/walk_scoring/walk_scoring?roomCode=${this.data.roomCode}`,
      imageUrl: ''
    }
  },

  onUnload() {
    if (this._loadingTimer) { clearTimeout(this._loadingTimer); this._loadingTimer = null }
    this._closeWatcher()
  },
  onReconnect() {
    if (this.data.roomCode) this._startWatch()
  },

  // ================================================================
  // 身份同步
  // ================================================================

  _waitReady(query, tries) {
    tries = tries || 0
    const app = getApp()
    if (app.globalData.openId) {
      const cache = wx.getStorageSync('__my_identity__') || {}
      this.setData({
        myOpenId: app.globalData.openId,
        myNickName: app.globalData.nickName || cache.nickName || '',
        myAvatarUrl: cache.avatarUrl || ''
      })
      this._afterIdentity(query)
      return
    }
    if (tries > IDENTITY_POLL_MAX) {
      wx.showToast({ title: '获取用户身份失败', icon: 'none' })
      this.setData({ loading: false })
      return
    }
    setTimeout(() => this._waitReady(query, tries + 1), IDENTITY_POLL_INTERVAL)
  },

  _afterIdentity(query) {
    if (!this.data.myNickName) {
      this.setData({ loading: false })
      return
    }
    // 从分享链接/首页进入（带 roomCode 或 roomId，统一走 joinRoom 云函数）
    if (query && (query.roomCode || query.roomId)) {
      this._doJoinRoom(query.roomCode || query.roomId)
      return
    }
    // 从首页创建进入
    if (query && query.action === 'create') {
      this.createRoom()
      return
    }
    // 本地优先：尝试从缓存瞬时恢复房间，后台云端校验
    const saved = wx.getStorageSync(STORAGE_WALK_ROOM)
    const cache = wx.getStorageSync('__walk_room_cache__')
    if (saved && saved.roomCode && cache && cache.roomCode === saved.roomCode) {
      // 瞬时展示缓存数据，无需 loading
      if (cache.players && cache.players.length > 0) this._sortSelfFirst(cache.players)
      this.setData({
        roomId: cache.roomId || saved.roomId,
        roomCode: cache.roomCode,
        isCreator: cache.isCreator || false,
        loading: false,
        players: cache.players || [],
        poolScore: cache.poolScore || 0,
        records: cache.records || [],
        verify: cache.verify !== undefined ? cache.verify : true,
        lastTakePlayer: cache.lastTakePlayer || null,
        fractionMode: cache.fractionMode || '',
        fractionAmount: cache.fractionAmount || 0,
        fractionTakenBy: cache.fractionTakenBy || []
      })
      // 后台静默拉取最新数据 + 启动实时监听
      this._loadRoomData()
      this._startWatch()
      return
    }
    // 有房间引用但无缓存 → 需重新加入
    if (saved && saved.roomCode) {
      wx.showModal({
        title: '恢复房间',
        content: `检测到房间 ${saved.roomCode}，是否重新连接？`,
        success: r => {
          if (r.confirm) this._doJoinRoom(saved.roomCode)
          else { wx.removeStorageSync(STORAGE_WALK_ROOM); this.setData({ loading: false }) }
        }
      })
    } else {
      this.setData({ loading: false })
    }
  },

  // ================================================================
  // 头像 + 昵称
  // ================================================================

  onChooseAvatar(e) {
    const tempUrl = e.detail.avatarUrl
    if (!tempUrl) return
    this.setData({ myAvatarUrl: tempUrl })
    const id = wx.getStorageSync('__my_identity__') || {}
    id.avatarUrl = tempUrl
    wx.setStorageSync('__my_identity__', id)
    if (wx.cloud) {
      wx.cloud.uploadFile({
        cloudPath: `avatars/${this.data.myOpenId}_${Date.now()}.png`,
        filePath: tempUrl,
        success: res => {
          const ident = wx.getStorageSync('__my_identity__') || {}
          ident.avatarUrl = res.fileID
          wx.setStorageSync('__my_identity__', ident)
          this.setData({ myAvatarUrl: res.fileID })
        }
      })
    }
  },

  onNickNameBlur(e) {
    const name = (e.detail.value || '').trim()
    if (name && name !== this.data.myNickName) {
      getApp().setNickName(name)
      this.setData({ myNickName: name })
    }
  },

  // ================================================================
  // 创建房间
  // ================================================================

  createRoom() {
    if (this.data.acting) return
    if (!this.data.myNickName) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' })
      return
    }
    this.setData({ acting: true })
    wx.showLoading({ title: '创建中...', mask: true })

    wx.cloud.callFunction({
      name: 'createRoom',
      data: {
        nickName: this.data.myNickName,
        avatarUrl: this.data.myAvatarUrl
      }
    }).then(res => {
      wx.hideLoading()
      this.setData({ acting: false })
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message, icon: 'none' })
        return
      }
      const roomId = res.result.roomId
      const roomCode = res.result.roomCode
      // 本地优先：构建初始房间状态，瞬时展示
      const initialPlayers = [{
        openId: this.data.myOpenId,
        nickName: this.data.myNickName,
        avatarUrl: this.data.myAvatarUrl,
        baseScore: 100,
        netScore: 100
      }]
      this._sortSelfFirst(initialPlayers)
      this.setData({
        roomId, roomCode, isCreator: true, loading: false,
        players: initialPlayers, poolScore: 0, records: []
      })
      // 写入持久化引用 + 完整缓存
      wx.setStorageSync(STORAGE_WALK_ROOM, { roomId, roomCode })
      wx.setStorageSync('__walk_room_cache__', {
        roomCode, roomId, isCreator: true,
        players: initialPlayers, poolScore: 0, records: [],
        verify: true, lastTakePlayer: null,
        fractionMode: '', fractionAmount: 0, fractionTakenBy: [],
        cachedAt: Date.now()
      })
      // 后台拉取权威数据 + 启动监听
      this._loadRoomData()
      this._startWatch()
    }).catch(err => {
      wx.hideLoading()
      this.setData({ acting: false })
      wx.showToast({ title: '创建失败: ' + (err.errMsg || '网络错误'), icon: 'none' })
    })
  },

  // ================================================================
  // 加入房间
  // ================================================================

  showJoinInput() {
    this.setData({ showJoinInput: true, joinRoomCode: '' })
  },

  cancelJoin() {
    this.setData({ showJoinInput: false, joinRoomCode: '' })
  },

  setJoinRoomCode(e) {
    const val = (e.detail.value || '').replace(/\D/g, '').slice(0, 6)
    this.setData({ joinRoomCode: val })
  },

  joinRoom() {
    const code = this.data.joinRoomCode
    if (!code) return
    if (code.length !== 6) {
      wx.showToast({ title: '房间号应为6位数字', icon: 'none' })
      return
    }
    this.setData({ showJoinInput: false, joinRoomCode: '' })
    this._doJoinRoom(code)
  },

  _doJoinRoom(roomCode) {
    if (!this.data.myNickName) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' })
      return
    }
    wx.showLoading({ title: '加入中...', mask: true })

    wx.cloud.callFunction({
      name: 'joinRoom',
      data: {
        roomCode: roomCode,
        nickName: this.data.myNickName,
        avatarUrl: this.data.myAvatarUrl
      }
    }).then(res => {
      wx.hideLoading()
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message, icon: 'none' })
        return
      }
      const roomId = res.result.roomId
      const roomCode = res.result.roomCode
      if (res.result.rejoined) {
        wx.showToast({ title: '欢迎回来！数据已恢复', icon: 'none' })
      }
      // 本地优先：利用 joinRoom 返回的完整数据直接构建 UI，跳过 getRoomInfo
      const roomData = res.result
      const players = roomData.players || []
      const poolScore = roomData.poolScore || 0
      const rawRecords = roomData.records || []
      // 格式化记录时间
      const formatTime = dateStr => {
        const d = new Date(dateStr)
        const h = String(d.getHours()).padStart(2, '0')
        const m = String(d.getMinutes()).padStart(2, '0')
        const s = String(d.getSeconds()).padStart(2, '0')
        return `${h}:${m}:${s}`
      }
      const records = rawRecords.map(r => ({ ...r, timeStr: formatTime(r.createTime) }))
      this._sortSelfFirst(players)
      this.setData({
        roomId, roomCode, isCreator: false, loading: false,
        players, poolScore, records, verify: true,
        fractionMode: roomData.fractionMode || '',
        fractionAmount: roomData.fractionAmount || 0,
        fractionTakenBy: roomData.fractionTakenBy || []
      })
      // 写入持久化引用 + 完整缓存
      wx.setStorageSync(STORAGE_WALK_ROOM, { roomId, roomCode })
      wx.setStorageSync('__walk_room_cache__', {
        roomCode, roomId, isCreator: false,
        players, poolScore, records, verify: true,
        lastTakePlayer: null,
        fractionMode: roomData.fractionMode || '',
        fractionAmount: roomData.fractionAmount || 0,
        fractionTakenBy: roomData.fractionTakenBy || [],
        cachedAt: Date.now()
      })
      // 后台拉取权威数据（含分数模式等精确计算）+ 启动监听
      this._loadRoomData()
      this._startWatch()
    }).catch(err => {
      wx.hideLoading()
      wx.showToast({ title: '加入失败: ' + (err.errMsg || '网络错误'), icon: 'none' })
    })
  },

  // ================================================================
  // 退出房间
  // ================================================================

  leaveRoom() {
    wx.showModal({
      title: '退出房间',
      content: '退出后可重新加入，数据保留',
      success: r => {
        if (r.confirm) {
          this._closeWatcher()
          wx.removeStorageSync(STORAGE_WALK_ROOM)
          wx.removeStorageSync('__walk_room_cache__')
          this.setData({
            roomId: '', roomCode: '', isCreator: false,
            players: [], poolScore: 0, records: [], verify: true,
            fractionMode: '', fractionAmount: 0, fractionTakenBy: []
          })
        }
      }
    })
  },

  // 结算：显示所有玩家剩余分数和底分
  showSettle() {
    this.setData({ showSettleDialog: true })
  },

  cancelSettle() {
    this.setData({ showSettleDialog: false })
  },

  // 确认结算 → 退出房间
  confirmSettle() {
    this.setData({ showSettleDialog: false })
    this._closeWatcher()
    wx.removeStorageSync(STORAGE_WALK_ROOM)
    wx.removeStorageSync('__walk_room_cache__')
    this.setData({
      roomId: '', roomCode: '', isCreator: false,
      players: [], poolScore: 0, records: [], verify: true,
      fractionMode: '', fractionAmount: 0, fractionTakenBy: []
    })
    wx.showToast({ title: '已结算并退出', icon: 'success' })
  },

  // ================================================================
  // 加载房间数据
  // ================================================================

  /** 将自己的头像排到玩家列表最前面 */
  _sortSelfFirst(players) {
    const myOpenId = this.data.myOpenId
    for (let i = 0; i < players.length; i++) {
      if (players[i].openId === myOpenId && i !== 0) {
        const me = players.splice(i, 1)[0]
        players.unshift(me)
        break
      }
    }
    return players
  },

  _loadRoomData(callback) {
    if (!this.data.roomCode) {
      if (callback) callback({ message: '无房间' }, false)
      return
    }
    // 是否静默刷新（已展示缓存数据时 loading 为 false）
    const silent = !this.data.loading
    console.log('[walk_scoring] _loadRoomData 开始, roomCode:', this.data.roomCode, 'silent:', silent)

    wx.cloud.callFunction({
      name: 'getRoomInfo',
      data: { roomCode: this.data.roomCode }
    }).then(res => {
      console.log('[walk_scoring] getRoomInfo 返回:', JSON.stringify({ ok: res.result.ok, message: res.result.message, playerCount: res.result.players && res.result.players.length, recordCount: res.result.records && res.result.records.length, poolScore: res.result.poolScore }))
      if (!res.result.ok) {
        // 房间可能已被删除
        if (res.result.message === '房间不存在') {
          this.leaveRoom()
        } else if (!silent) {
          // 非静默模式才显示错误 toast
          wx.showToast({ title: res.result.message || '加载失败', icon: 'none' })
        }
        this.setData({ loading: false })
        if (callback) callback({ message: res.result.message || '加载失败' }, false)
        return
      }
      const { room, players, poolScore, records, verify } = res.result
      // 提取服务端分数锁定状态
      const fractionMode = room.fractionMode || ''
      const fractionAmount = room.fractionAmount || 0
      const fractionTakenBy = room.fractionTakenBy || []
      // 格式化记录时间
      const formatTime = dateStr => {
        const d = new Date(dateStr)
        const h = String(d.getHours()).padStart(2, '0')
        const m = String(d.getMinutes()).padStart(2, '0')
        const s = String(d.getSeconds()).padStart(2, '0')
        return `${h}:${m}:${s}`
      }
      const formattedRecords = records.map(r => ({
        ...r,
        timeStr: formatTime(r.createTime)
      }))

      // 最近一次取分玩家（用于公共池展示）
      let lastTakePlayer = this.data.lastTakePlayer
      // records 已按 createTime desc（最新在前）返回，直接 find 即取最近一次取分，无需 reverse
      const lastDown = records.find(r => r.type === 'down')
      if (lastDown) {
        const lp = players.find(p => p.openId === lastDown.playerOpenId)
        if (lp) {
          lastTakePlayer = { openId: lp.openId, avatarUrl: lp.avatarUrl || '', nickName: lp.nickName }
        } else {
          lastTakePlayer = null
        }
      } else {
        lastTakePlayer = null
      }
      const isCreator = room.creatorOpenId === this.data.myOpenId

      this._sortSelfFirst(players)

      this.setData({
        loading: false,
        isCreator,
        players, poolScore, records: formattedRecords, verify,
        lastTakePlayer,
        fractionMode, fractionAmount, fractionTakenBy
      })

      // 写入完整缓存，供下次瞬时恢复
      wx.setStorageSync('__walk_room_cache__', {
        roomCode: this.data.roomCode, roomId: this.data.roomId, isCreator,
        players, poolScore, records: formattedRecords, verify,
        lastTakePlayer,
        fractionMode, fractionAmount, fractionTakenBy,
        cachedAt: Date.now()
      })

      if (callback) callback(null, true)
    }).catch(err => {
      console.error('加载房间数据失败:', err)
      this.setData({ loading: false })
      if (!silent) {
        wx.showToast({ title: '加载失败，请下拉刷新', icon: 'none' })
      }
      if (callback) callback(err, false)
    })
  },

  /** 手动刷新房间数据 */
  refreshRoom() {
    if (!this.data.roomCode) return
    wx.showLoading({ title: '刷新中...', mask: false })
    this._loadRoomData((err, ok) => {
      wx.hideLoading()
      if (ok) {
        wx.showToast({ title: '已刷新', icon: 'success', duration: 1200 })
      } else {
        wx.showToast({ title: '刷新云端数据失败', icon: 'none' })
      }
    })
  },

  // ================================================================
  // 实时监听 score_records 变化 → 自动刷新
  // ================================================================

  _startWatch() {
    if (!this.data.roomId || !wx.cloud) return
    this._closeWatcher()

    const db = wx.cloud.database()
    this._watcher = db.collection('score_records')
      .where({ roomId: this.data.roomId })
      .watch({
        onChange: () => {
          // 后台同步进行中 → 跳过，等最终同步完成后统一重载
          if (this.data._pendingSyncs > 0) return
          this._loadRoomData()
        },
        onError: err => {
          console.error('watch 异常:', err)
        }
      })
  },

  _closeWatcher() {
    if (this._watcher) {
      try { this._watcher.close() } catch (e) { /* ignore */ }
      this._watcher = null
    }
  },

  // ================================================================
  // 乐观更新：本地预计算分数，立即 setData，后台异步同步云函数
  // ================================================================

  // 通用上分/取分乐观更新（addScoreRecord）
  _applyOptimisticScore(type, score, targetOpenId) {
    const players = this.data.players
    const playerIdx = players.findIndex(p => p.openId === targetOpenId)
    if (playerIdx < 0) return null

    const player = players[playerIdx]
    const poolDelta = type === 'up' ? score : -score
    const playerDelta = type === 'up' ? -score : score
    const newPoolScore = this.data.poolScore + poolDelta
    const newNetScore = player.netScore + playerDelta

    const updates = {
      poolScore: newPoolScore,
      ['players[' + playerIdx + '].netScore']: newNetScore
    }
    // 上分时清除平分锁（云函数 addScoreRecord 也会清，前端乐观同步）
    if (type === 'up') {
      updates.fractionMode = ''
      updates.fractionAmount = 0
      updates.fractionTakenBy = []
    }

    this.setData(updates)
    return { playerIdx, newPoolScore, newNetScore }
  },

  // 加底分乐观更新
  _applyOptimisticBaseScore(targetOpenId) {
    const players = this.data.players
    const playerIdx = players.findIndex(p => p.openId === targetOpenId)
    if (playerIdx < 0) return null

    const player = players[playerIdx]
    const newBase = player.baseScore + 100
    const newNet = player.netScore + 100

    this.setData({
      ['players[' + playerIdx + '].baseScore']: newBase,
      ['players[' + playerIdx + '].netScore']: newNet
    })
    return { playerIdx, newBase, newNet }
  },

  // 后台同步云函数（不阻塞 UI）
  _backgroundSync(params) {
    const syncId = Date.now()
    this._syncId = syncId
    this.setData({ _pendingSyncs: this.data._pendingSyncs + 1 })

    wx.cloud.callFunction(params).then(res => {
      const remaining = this.data._pendingSyncs - 1
      const isLatest = this._syncId === syncId
      if (isLatest) this._syncId = 0

      if (!res.result.ok && isLatest) {
        // 服务端校验失败 → 拉取真实数据修正本地
        this.setData({ _pendingSyncs: remaining })
        wx.showToast({ title: res.result.message, icon: 'none' })
        this._loadRoomData()
        return
      }

      // 所有同步完成 → 以服务端数据为准最终确认
      if (remaining <= 0) {
        this.setData({ _pendingSyncs: 0 })
        this._loadRoomData()
      } else {
        this.setData({ _pendingSyncs: remaining })
      }
    }).catch(err => {
      const remaining = this.data._pendingSyncs - 1
      const isLatest = this._syncId === syncId
      if (isLatest) this._syncId = 0

      if (isLatest) {
        // 网络异常 → 拉取服务端数据修复本地乐观更新
        console.error('[walk_scoring] 后台同步失败:', err)
        this.setData({ _pendingSyncs: remaining })
        wx.showToast({ title: '网络异常，数据可能未保存', icon: 'none' })
        this._loadRoomData()
        return
      }

      if (remaining <= 0) {
        this.setData({ _pendingSyncs: 0 })
        this._loadRoomData()
      } else {
        this.setData({ _pendingSyncs: remaining })
      }
    })
  },

  // ================================================================
  // 计分操作
  // ================================================================

  // 点击成员头像 → 显示当前底分
  showPlayerBaseScore(e) {
    const { nickname, base, net } = e.currentTarget.dataset
    wx.showModal({
      title: nickname || '玩家',
      content: `底分：${base}\n净分：${net >= 0 ? '+' : ''}${net}`,
      showCancel: false,
      confirmText: '知道了'
    })
  },

  // 点击玩家头像 → 转账（参考麻将计分逻辑）
  onPlayerAvatarTap(e) {
    const { openid, nickname, avatar } = e.currentTarget.dataset
    // 不能转给自己
    if (openid === this.data.myOpenId) {
      wx.showToast({ title: '不能转分给自己，请使用取分按钮', icon: 'none' })
      return
    }
    this.setData({
      showTransfer: true,
      transferTargetOpenId: openid || '',
      transferTargetName: nickname || '玩家',
      transferTargetAvatar: avatar || '',
      transferAmount: ''
    })
  },

  // 转账弹窗 — 数字键盘按键
  onTransferKpadTap(e) {
    const key = e.currentTarget.dataset.key
    let cur = this.data.transferAmount || ''
    // 限制最多 8 位数
    if (cur.replace(/\D/g, '').length >= 8) return
    // 首位不能是多个 0
    if (cur === '0' && key !== '00') cur = ''
    const next = cur + key
    this.setData({ transferAmount: next })
  },

  // 转账弹窗 — 退格键
  onTransferKpadDelete() {
    const cur = this.data.transferAmount || ''
    if (cur.length <= 1) {
      this.setData({ transferAmount: '' })
      return
    }
    this.setData({ transferAmount: cur.slice(0, -1) })
  },

  // 转账弹窗 — 取消
  cancelTransfer() {
    this.setData({ showTransfer: false, transferTargetOpenId: '', transferTargetName: '', transferTargetAvatar: '', transferAmount: '' })
  },

  // 转账弹窗 — 确认（走 addScoreRecord，type=down，目标=收款玩家）
  confirmTransfer() {
    const amount = parseInt(this.data.transferAmount) || 0
    if (amount <= 0) {
      wx.showToast({ title: '请输入有效的转账金额', icon: 'none' })
      return
    }
    if (amount > this.data.poolScore) {
      wx.showToast({ title: `公共池仅剩${this.data.poolScore}分`, icon: 'none' })
      return
    }
    if (this.data.acting) return
    this.setData({ acting: true })

    const targetOpenId = this.data.transferTargetOpenId
    const targetName = this.data.transferTargetName

    console.log('[walk_scoring] confirmTransfer:', { amount, targetOpenId, targetName })

    // 1. 本地乐观更新 UI
    const local = this._applyOptimisticScore('down', amount, targetOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
      return
    }

    // 2. 更新最近取分玩家、关闭弹窗
    this.setData({
      showTransfer: false,
      transferTargetOpenId: '',
      transferTargetName: '',
      transferTargetAvatar: '',
      transferAmount: '',
      acting: false,
      lastTakePlayer: {
        openId: targetOpenId,
        avatarUrl: this.data.transferTargetAvatar,
        nickName: targetName
      }
    })

    // 3. 显示操作结果
    wx.showToast({ title: `转分 ${amount} → ${targetName}`, icon: 'success', duration: 1200 })

    // 4. 后台异步同步到云函数
    this._backgroundSync({
      name: 'addScoreRecord',
      data: {
        roomCode: this.data.roomCode,
        type: 'down',
        score: amount,
        targetPlayerOpenId: targetOpenId
      }
    })
  },

  // 按玩家筛选流水记录
  filterRecordsByPlayer(e) {
    const openId = e.currentTarget.dataset.openid
    // 再次点击同一头像 → 取消筛选
    if (this.data.recordFilterOpenId === openId) {
      this.setData({ recordFilterOpenId: '' })
    } else {
      this.setData({ recordFilterOpenId: openId })
    }
  },

  clearRecordFilter() {
    this.setData({ recordFilterOpenId: '' })
  },

  // 快捷上分按钮（给自己上分）
  quickScoreSelf(e) {
    const val = Number(e.currentTarget.dataset.val)
    if (!val || val <= 0) return
    const me = this.data.players.find(p => p.openId === this.data.myOpenId)
    if (!me) return
    console.log('[walk_scoring] quickScoreSelf:', val)
    this._executeScoreAction('up', val, this.data.myOpenId, me.nickName)
  },

  // 自定义上分弹窗（点击头像触发）
  showCustomUpScore() {
    this.setData({ showCustomUpDialog: true, customUpAmount: '' })
  },
  setCustomUpAmount(e) {
    const val = (e.detail.value || '').replace(/\D/g, '')
    this.setData({ customUpAmount: val })
  },
  confirmCustomUpScore() {
    const score = Number(this.data.customUpAmount)
    if (!score || score <= 0 || !Number.isInteger(score)) {
      wx.showToast({ title: '请输入正整数', icon: 'none' })
      return
    }
    const me = this.data.players.find(p => p.openId === this.data.myOpenId)
    if (!me) return
    this.setData({ showCustomUpDialog: false, customUpAmount: '' })
    this._executeScoreAction('up', score, this.data.myOpenId, me.nickName)
  },
  cancelCustomUpScore() {
    this.setData({ showCustomUpDialog: false, customUpAmount: '' })
  },

  // ================================================================
  // 公共池取分操作（取全部 / 取1/2 / 取1/3）
  // ================================================================

  // 取全部：清空公共池，走 takeFromPool 云函数，同步清锁
  takeAll() {
    if (this.data.poolScore <= 0) {
      wx.showToast({ title: '公共池没有可取的分数', icon: 'none' })
      return
    }
    if (this.data.acting) return
    let content = `确定将公共池 ${this.data.poolScore} 分全部取出？`
    if (this.data.fractionMode) {
      content += '\n⚠ 将清除当前分数锁定'
    }
    wx.showModal({
      title: '取全部',
      content: content,
      success: r => {
        if (r.confirm) {
          this._executePoolTake('all')
        }
      }
    })
  },

  // 取½：首次触发锁定基数 Math.floor(pool/2)，后续同模式复用固定值
  takeHalf() {
    if (this.data.acting) return
    const myOpenId = this.data.myOpenId
    const { fractionMode, fractionAmount, fractionTakenBy, poolScore } = this.data

    // 对方模式已锁 → 按钮置灰 + toast 拒绝
    if (fractionMode === 'third') {
      wx.showToast({ title: '当前已锁定取⅓模式，无法取½', icon: 'none' })
      return
    }
    // 已取过 → toast 拒绝（防止重复取）
    if (fractionMode === 'half' && fractionTakenBy.includes(myOpenId)) {
      wx.showToast({ title: '你已经取过½了', icon: 'none' })
      return
    }
    // 计算金额
    let amount
    if (fractionMode === 'half') {
      amount = fractionAmount  // 已锁，使用固定值
    } else {
      amount = Math.floor(poolScore / 2)  // 首次触发，计算基数
      if (amount <= 0) {
        wx.showToast({ title: '公共池不足以取½', icon: 'none' })
        return
      }
    }
    wx.showModal({
      title: '取½',
      content: `确定从公共池取 ${amount} 分（一半）？`,
      success: r => {
        if (r.confirm) {
          this._executePoolTake('half')
        }
      }
    })
  },

  // 取⅓：首次触发锁定基数 Math.floor(pool/3)，后续同模式复用固定值
  takeThird() {
    if (this.data.acting) return
    const myOpenId = this.data.myOpenId
    const { fractionMode, fractionAmount, fractionTakenBy, poolScore } = this.data

    // 对方模式已锁 → 按钮置灰 + toast 拒绝
    if (fractionMode === 'half') {
      wx.showToast({ title: '当前已锁定取½模式，无法取⅓', icon: 'none' })
      return
    }
    // 已取过 → toast 拒绝（防止重复取）
    if (fractionMode === 'third' && fractionTakenBy.includes(myOpenId)) {
      wx.showToast({ title: '你已经取过⅓了', icon: 'none' })
      return
    }
    // 计算金额
    let amount
    if (fractionMode === 'third') {
      amount = fractionAmount  // 已锁，使用固定值
    } else {
      amount = Math.floor(poolScore / 3)  // 首次触发，计算基数
      if (amount <= 0) {
        wx.showToast({ title: '公共池不足以取⅓', icon: 'none' })
        return
      }
    }
    wx.showModal({
      title: '取⅓',
      content: `确定从公共池取 ${amount} 分（三分之一）？`,
      success: r => {
        if (r.confirm) {
          this._executePoolTake('third')
        }
      }
    })
  },

  // 谁点谁取，走 addScoreRecord（type=down）
  showCustomTake() {
    if (this.data.poolScore <= 0) {
      wx.showToast({ title: '公共池没有可取的分数', icon: 'none' })
      return
    }
    this.setData({
      showCustomTakeDialog: true,
      customTakeAmount: ''
    })
  },

  cancelCustomTake() {
    this.setData({ showCustomTakeDialog: false, customTakeAmount: '' })
  },

  setCustomTakeAmount(e) {
    const val = (e.detail.value || '').replace(/\D/g, '')
    this.setData({ customTakeAmount: val })
  },

  confirmCustomTake() {
    const amount = Number(this.data.customTakeAmount)
    if (!amount || amount <= 0 || !Number.isInteger(amount)) {
      wx.showToast({ title: '请输入正整数', icon: 'none' })
      return
    }
    if (amount > this.data.poolScore) {
      wx.showToast({ title: `公共池仅剩${this.data.poolScore}分`, icon: 'none' })
      return
    }
    wx.showModal({
      title: '自定义取分',
      content: `确定从公共池取 ${amount} 分？`,
      success: r => {
        if (r.confirm) {
          this._executeCustomTake(amount)
        }
      }
    })
  },

  // 自定义取分调用 addScoreRecord（type=down），谁点谁取
  _executeCustomTake(amount) {
    if (this.data.acting) return
    this.setData({ acting: true })

    const myOpenId = this.data.myOpenId
    const me = this.data.players.find(p => p.openId === myOpenId)
    const myName = me ? me.nickName : '我'

    console.log('[walk_scoring] _executeCustomTake:', { amount, myOpenId })

    // 1. 本地乐观更新 UI（即时响应）
    const local = this._applyOptimisticScore('down', amount, myOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
      return
    }

    // 2. 更新最近取分玩家（用于公共池展示头像）
    this.setData({
      showCustomTakeDialog: false,
      customTakeAmount: '',
      acting: false,
      lastTakePlayer: {
        openId: myOpenId,
        avatarUrl: me ? (me.avatarUrl || '') : '',
        nickName: myName
      }
    })

    // 3. 显示操作结果
    wx.showToast({ title: `取分 ${amount} → ${myName}`, icon: 'success', duration: 1200 })

    // 4. 后台异步同步到云函数（不阻塞 UI）
    this._backgroundSync({
      name: 'addScoreRecord',
      data: {
        roomCode: this.data.roomCode,
        type: 'down',
        score: amount,
        targetPlayerOpenId: myOpenId
      }
    })
  },

  // 取全部/取½/取⅓ 走 takeFromPool 云函数（同步，服务端原子锁）
  _executePoolTake(mode) {
    if (this.data.acting) return
    this.setData({ acting: true })
    wx.showLoading({ title: '处理中...', mask: true })

    const myOpenId = this.data.myOpenId

    wx.cloud.callFunction({
      name: 'takeFromPool',
      data: {
        roomCode: this.data.roomCode,
        targetPlayerOpenId: myOpenId,
        mode: mode
      }
    }).then(res => {
      wx.hideLoading()
      this.setData({ acting: false })

      if (!res.result.ok) {
        wx.showToast({ title: res.result.message || '取分失败', icon: 'none', duration: 2000 })
        // 同步失败 → 重新拉取服务端数据修复本地
        this._loadRoomData()
        return
      }

      const result = res.result
      const me = this.data.players.find(p => p.openId === myOpenId)
      const myName = me ? me.nickName : '我'

      // 乐观更新本地 state（服务端已写入，这里做本地同步）
      const updates = {
        poolScore: result.poolScore,
        fractionMode: result.fractionMode || '',
        fractionAmount: result.fractionAmount || 0,
        fractionTakenBy: result.takenBy || []
      }

      // 更新本人 netScore
      const myIdx = this.data.players.findIndex(p => p.openId === myOpenId)
      if (myIdx >= 0) {
        const newNet = this.data.players[myIdx].netScore + result.takeAmount
        updates['players[' + myIdx + '].netScore'] = newNet
      }

      // 更新最近取分玩家
      updates.lastTakePlayer = {
        openId: myOpenId,
        avatarUrl: me ? (me.avatarUrl || '') : '',
        nickName: myName
      }

      this.setData(updates)

      // 提示信息
      const modeLabel = mode === 'all' ? '全部' : (mode === 'half' ? '½' : '⅓')
      wx.showToast({ title: `取${modeLabel} ${result.takeAmount}分 → ${myName}`, icon: 'success', duration: 1500 })

      // 延迟拉取服务端数据做最终确认（确保 netScore 等精确）
      setTimeout(() => {
        this._loadRoomData()
      }, 800)
    }).catch(err => {
      wx.hideLoading()
      this.setData({ acting: false })
      console.error('[walk_scoring] _executePoolTake 异常:', err)
      wx.showToast({ title: '网络异常，取分失败', icon: 'none' })
      this._loadRoomData()
    })
  },


  // 从房间栏给自己加底分
  addBaseScoreSelf() {
    const me = this.data.players.find(p => p.openId === this.data.myOpenId)
    if (!me) return
    console.log('[walk_scoring] addBaseScoreSelf')
    wx.showModal({
      title: '增加底分',
      content: `确定给自己增加100底分？\n当前底分：${me.baseScore} → 增加后：${me.baseScore + 100}`,
      success: r => {
        if (r.confirm) {
          this._doAddBaseScore(this.data.myOpenId)
        }
      }
    })
  },

  // 给玩家增加100底分
  addBaseScore(e) {
    const { openid, nickname } = e.currentTarget.dataset
    console.log('[walk_scoring] addBaseScore, dataset:', JSON.stringify(e.currentTarget.dataset))

    const player = this.data.players.find(p => p.openId === (openid || ''))
    const currentBase = player ? player.baseScore : 100
    const targetName = nickname || (player && player.nickName) || ''

    wx.showModal({
      title: '增加底分',
      content: `确定给 ${targetName} 增加100底分？\n当前底分：${currentBase} → 增加后：${currentBase + 100}`,
      success: r => {
        if (r.confirm) {
          this._doAddBaseScore(openid || '')
        }
      }
    })
  },

  _doAddBaseScore(targetOpenId) {
    if (this.data.acting) return
    this.setData({ acting: true })

    console.log('[walk_scoring] _doAddBaseScore:', { targetOpenId })

    // 1. 本地乐观更新 UI（即时响应）
    const local = this._applyOptimisticBaseScore(targetOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '目标玩家不在房间中', icon: 'none' })
      return
    }

    // 2. 释放防重复锁
    this.setData({ acting: false })

    // 3. 显示操作结果
    wx.showToast({ title: '底分+100', icon: 'success', duration: 1000 })

    // 4. 后台异步同步到云函数（不阻塞 UI）
    this._backgroundSync({
      name: 'addBaseScore',
      data: {
        roomCode: this.data.roomCode,
        targetPlayerOpenId: targetOpenId
      }
    })
  },

  // 阻止事件冒泡（catchtap 空函数在某些基础库版本不稳定，改为实函数）
  _preventBubble() {},

  // 通用计分执行（上分/取分共用）
  _executeScoreAction(type, score, targetOpenId, targetName) {
    if (this.data.acting) {
      console.log('[walk_scoring] _executeScoreAction 防重复点击拦截')
      return
    }
    this.setData({ acting: true })

    console.log('[walk_scoring] _executeScoreAction:', { roomCode: this.data.roomCode, type, score, targetOpenId })

    // 1. 本地乐观更新 UI（即时响应）
    const local = this._applyOptimisticScore(type, score, targetOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '目标玩家不在房间中', icon: 'none' })
      return
    }

    // 2. 释放防重复锁
    this.setData({ acting: false })

    // 3. 后台异步同步到云函数（不阻塞 UI）
    this._backgroundSync({
      name: 'addScoreRecord',
      data: {
        roomCode: this.data.roomCode,
        type: type,
        score: score,
        targetPlayerOpenId: targetOpenId
      }
    })
  },

  // ================================================================
  // 复制房间号
  // ================================================================

  copyRoomCode() {
    wx.setClipboardData({
      data: this.data.roomCode,
      success: () => {
        wx.showToast({ title: '房间号已复制', icon: 'success' })
      }
    })
  }
})
