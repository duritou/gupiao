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
    // 公共池取分
    fractionMode: null,      // null | 'half' | 'third'
    fractionAmount: 0,       // 锁定后的每人取分值
    fractionTakenBy: [],     // 已取分玩家 openId 列表
    fractionTakenCount: 0,   // 已取人数
    fractionTotalSlots: 0,   // 模式总人数（2或3）
    poolRemainder: 0,        // 1/2 或 1/3 模式下的余数
    halfAmount: 0,           // 当前可取 1/2 的金额
    thirdAmount: 0,          // 当前可取 1/3 的金额
    poolTargetOpenId: '',    // 选中的取分目标玩家
    poolTargetAvatar: '',    // 选中目标的头像
    poolTargetName: '',      // 选中目标的昵称
    // UI
    showJoinInput: false,
    joinRoomCode: '',
    // 自定义上分弹窗（点击头像）
    showCustomUpDialog: false,
    customUpAmount: '',
    // 自定义取分弹窗
    showCustomTakeDialog: false,
    customTakeAmount: '',
    customTakeTargetName: '',
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
        fractionMode: cache.fractionMode || null,
        fractionAmount: cache.fractionAmount || 0,
        fractionTakenBy: cache.fractionTakenBy || [],
        fractionTakenCount: cache.fractionTakenCount || 0,
        fractionTotalSlots: cache.fractionTotalSlots || 0,
        halfAmount: cache.halfAmount || 0,
        thirdAmount: cache.thirdAmount || 0,
        poolRemainder: cache.poolRemainder || 0,
        poolTargetOpenId: cache.poolTargetOpenId || '',
        poolTargetAvatar: cache.poolTargetAvatar || '',
        poolTargetName: cache.poolTargetName || ''
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
        verify: true, fractionMode: null, fractionAmount: 0,
        fractionTakenBy: [], fractionTakenCount: 0, fractionTotalSlots: 0,
        halfAmount: 0, thirdAmount: 0, poolRemainder: 0,
        poolTargetOpenId: '', poolTargetAvatar: '', poolTargetName: '',
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
        players, poolScore, records, verify: true
      })
      // 写入持久化引用 + 完整缓存
      wx.setStorageSync(STORAGE_WALK_ROOM, { roomId, roomCode })
      wx.setStorageSync('__walk_room_cache__', {
        roomCode, roomId, isCreator: false,
        players, poolScore, records, verify: true,
        fractionMode: null, fractionAmount: 0,
        fractionTakenBy: [], fractionTakenCount: 0, fractionTotalSlots: 0,
        halfAmount: 0, thirdAmount: 0, poolRemainder: 0,
        poolTargetOpenId: '', poolTargetAvatar: '', poolTargetName: '',
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
            players: [], poolScore: 0, records: [], verify: true
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
      players: [], poolScore: 0, records: [], verify: true
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

      // 计算公共池取分相关数据
      const fractionMode = room.fractionMode || null
      const fractionAmount = room.fractionAmount || 0
      const fractionTakenBy = room.fractionTakenBy || []
      const fractionTotalSlots = fractionMode === 'half' ? 2 : fractionMode === 'third' ? 3 : 0
      const fractionTakenCount = fractionTakenBy.length
      const halfAmount = fractionMode === 'half' ? fractionAmount : Math.floor(poolScore / 2)
      const thirdAmount = fractionMode === 'third' ? fractionAmount : Math.floor(poolScore / 3)
      // 余数：锁定模式下，公共池分数对每人可取量的模（即全部取完后池中剩余）
      const poolRemainder = fractionMode && fractionAmount > 0 ? poolScore % fractionAmount : 0
      // 如果已有选中的取分目标但该玩家已不在房间，则清空
      let poolTargetOpenId = this.data.poolTargetOpenId
      if (poolTargetOpenId && !players.find(p => p.openId === poolTargetOpenId)) {
        poolTargetOpenId = players.length > 0 ? players[0].openId : ''
      } else if (!poolTargetOpenId && players.length > 0) {
        poolTargetOpenId = players[0].openId
      }
      // 计算选中目标的头像和昵称
      const targetPlayer = poolTargetOpenId ? players.find(p => p.openId === poolTargetOpenId) : null
      const poolTargetAvatar = targetPlayer ? targetPlayer.avatarUrl || '' : ''
      const poolTargetName = targetPlayer ? targetPlayer.nickName || '' : ''
      const isCreator = room.creatorOpenId === this.data.myOpenId

      this._sortSelfFirst(players)

      this.setData({
        loading: false,
        isCreator,
        players, poolScore, records: formattedRecords, verify,
        fractionMode, fractionAmount, fractionTakenBy,
        fractionTakenCount, fractionTotalSlots,
        halfAmount, thirdAmount, poolRemainder,
        poolTargetOpenId, poolTargetAvatar, poolTargetName
      })

      // 写入完整缓存，供下次瞬时恢复
      wx.setStorageSync('__walk_room_cache__', {
        roomCode: this.data.roomCode, roomId: this.data.roomId, isCreator,
        players, poolScore, records: formattedRecords, verify,
        fractionMode, fractionAmount, fractionTakenBy,
        fractionTakenCount, fractionTotalSlots,
        halfAmount, thirdAmount, poolRemainder,
        poolTargetOpenId, poolTargetAvatar, poolTargetName,
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

    // 上分时重置分数模式（公共池基数变化，旧锁定失效）
    if (type === 'up' && this.data.fractionMode) {
      const newHalf = Math.floor(newPoolScore / 2)
      const newThird = Math.floor(newPoolScore / 3)
      Object.assign(updates, {
        fractionMode: null, fractionAmount: 0, fractionTakenBy: [],
        fractionTakenCount: 0, fractionTotalSlots: 0, poolRemainder: 0,
        halfAmount: newHalf, thirdAmount: newThird
      })
    }

    this.setData(updates)
    return { playerIdx, newPoolScore, newNetScore }
  },

  // 公共池取分乐观更新（takeFromPool，含分数模式锁定追踪）
  _applyOptimisticTakeFromPool(mode, targetOpenId) {
    const players = this.data.players
    const playerIdx = players.findIndex(p => p.openId === targetOpenId)
    if (playerIdx < 0) return null

    let takeAmount
    if (mode === 'all') {
      takeAmount = this.data.poolScore
    } else {
      // 已锁定则用锁定金额，首次触发取当前计算值
      takeAmount = this.data.fractionMode === mode
        ? this.data.fractionAmount
        : this.data[mode === 'half' ? 'halfAmount' : 'thirdAmount']
    }
    if (takeAmount <= 0) return null

    const newPoolScore = this.data.poolScore - takeAmount
    const newNetScore = players[playerIdx].netScore + takeAmount

    const updates = {
      poolScore: newPoolScore,
      ['players[' + playerIdx + '].netScore']: newNetScore
    }

    // 分数模式追踪
    if (mode === 'all') {
      Object.assign(updates, {
        fractionMode: null, fractionAmount: 0, fractionTakenBy: [],
        fractionTakenCount: 0, fractionTotalSlots: 0, poolRemainder: 0,
        halfAmount: Math.floor(newPoolScore / 2),
        thirdAmount: Math.floor(newPoolScore / 3)
      })
    } else {
      const divisor = mode === 'half' ? 2 : 3
      const takenBy = [...this.data.fractionTakenBy]
      if (!takenBy.includes(targetOpenId)) {
        takenBy.push(targetOpenId)
      }

      if (takenBy.length >= divisor) {
        // 本轮取完 → 自动重置
        Object.assign(updates, {
          fractionMode: null, fractionAmount: 0, fractionTakenBy: [],
          fractionTakenCount: 0, fractionTotalSlots: 0, poolRemainder: 0,
          halfAmount: Math.floor(newPoolScore / 2),
          thirdAmount: Math.floor(newPoolScore / 3)
        })
      } else {
        updates.fractionTakenBy = takenBy
        updates.fractionTakenCount = takenBy.length
        if (!this.data.fractionMode) {
          // 首次触发 → 锁定
          updates.fractionMode = mode
          updates.fractionAmount = takeAmount
          updates.fractionTotalSlots = divisor
          updates.halfAmount = mode === 'half' ? takeAmount : this.data.halfAmount
          updates.thirdAmount = mode === 'third' ? takeAmount : this.data.thirdAmount
        }
        // 已锁定模式下 poolRemainder 不变（每次取固定金额）
      }
    }

    this.setData(updates)
    return { playerIdx, takeAmount, newPoolScore }
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
    if (!this.data.isCreator) {
      wx.showToast({ title: '仅房主可操作', icon: 'none' })
      return
    }
    const val = Number(e.currentTarget.dataset.val)
    if (!val || val <= 0) return
    const me = this.data.players.find(p => p.openId === this.data.myOpenId)
    if (!me) return
    console.log('[walk_scoring] quickScoreSelf:', val)
    this._executeScoreAction('up', val, this.data.myOpenId, me.nickName)
  },

  // 自定义上分弹窗（点击头像触发）
  showCustomUpScore() {
    if (!this.data.isCreator) return
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

  // 选择取分目标玩家
  selectPoolTarget(e) {
    const openid = e.currentTarget.dataset.openid
    if (openid) {
      const player = this.data.players.find(p => p.openId === openid)
      this.setData({
        poolTargetOpenId: openid,
        poolTargetAvatar: player ? player.avatarUrl || '' : '',
        poolTargetName: player ? player.nickName || '' : ''
      })
    }
  },

  // 点击取分目标头像：在玩家间循环切换
  cyclePoolTarget() {
    const { players, poolTargetOpenId } = this.data
    if (!players.length) return
    const idx = players.findIndex(p => p.openId === poolTargetOpenId)
    const nextIdx = idx < 0 ? 0 : (idx + 1) % players.length
    const next = players[nextIdx]
    this.setData({
      poolTargetOpenId: next.openId,
      poolTargetAvatar: next.avatarUrl || '',
      poolTargetName: next.nickName || ''
    })
  },

  // 取全部：公共池所有分数给选中玩家
  takeAll() {
    if (!this.data.isCreator) return
    if (this.data.poolScore <= 0) {
      wx.showToast({ title: '公共池没有可取的分数', icon: 'none' })
      return
    }
    const target = this.data.players.find(p => p.openId === this.data.poolTargetOpenId)
    const targetName = target ? target.nickName : ''
    if (!targetName) {
      wx.showToast({ title: '请先选择取分玩家', icon: 'none' })
      return
    }
    wx.showModal({
      title: '取全部',
      content: `确定将公共池 ${this.data.poolScore} 分全部给 ${targetName}？`,
      success: r => {
        if (r.confirm) {
          this._doTakeFromPool('all', this.data.poolScore, targetName)
        }
      }
    })
  },

  // 取1/2：取一半给选中玩家（首次触发锁定金额）
  takeHalf() {
    if (!this.data.isCreator) return
    if (this.data.fractionMode && this.data.fractionMode !== 'half') return // 已锁定为1/3，不可切换
    const amount = this.data.halfAmount
    if (amount <= 0) {
      wx.showToast({ title: '公共池不足以取1/2', icon: 'none' })
      return
    }
    const target = this.data.players.find(p => p.openId === this.data.poolTargetOpenId)
    const targetName = target ? target.nickName : ''
    if (!targetName) {
      wx.showToast({ title: '请先选择取分玩家', icon: 'none' })
      return
    }
    const modeLabel = this.data.fractionMode === 'half' ? '（已锁定）' : '（首次触发，后续每人固定取' + amount + '分）'
    wx.showModal({
      title: '取1/2',
      content: `确定从公共池取 ${amount} 分给 ${targetName}？\n${modeLabel}`,
      success: r => {
        if (r.confirm) {
          this._doTakeFromPool('half', amount, targetName)
        }
      }
    })
  },

  // 取1/3：取三分之一给选中玩家（首次触发锁定金额）
  takeThird() {
    if (!this.data.isCreator) return
    if (this.data.fractionMode && this.data.fractionMode !== 'third') return // 已锁定为1/2，不可切换
    const amount = this.data.thirdAmount
    if (amount <= 0) {
      wx.showToast({ title: '公共池不足以取1/3', icon: 'none' })
      return
    }
    const target = this.data.players.find(p => p.openId === this.data.poolTargetOpenId)
    const targetName = target ? target.nickName : ''
    if (!targetName) {
      wx.showToast({ title: '请先选择取分玩家', icon: 'none' })
      return
    }
    const modeLabel = this.data.fractionMode === 'third' ? '（已锁定）' : '（首次触发，后续每人固定取' + amount + '分）'
    wx.showModal({
      title: '取1/3',
      content: `确定从公共池取 ${amount} 分给 ${targetName}？\n${modeLabel}`,
      success: r => {
        if (r.confirm) {
          this._doTakeFromPool('third', amount, targetName)
        }
      }
    })
  },

  // 通用：调用 takeFromPool 云函数
  _doTakeFromPool(mode, amount, targetName) {
    if (this.data.acting) return
    this.setData({ acting: true })

    console.log('[walk_scoring] _doTakeFromPool:', { mode, amount, targetName, targetId: this.data.poolTargetOpenId })

    // 1. 本地乐观更新 UI（即时响应）
    const local = this._applyOptimisticTakeFromPool(mode, this.data.poolTargetOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
      return
    }

    // 2. 释放防重复锁
    this.setData({ acting: false })

    // 3. 显示操作结果
    const modeLabel = mode === 'all' ? '取全部' : mode === 'half' ? '取1/2' : '取1/3'
    wx.showToast({ title: `${modeLabel} ${local.takeAmount} → ${targetName}`, icon: 'success', duration: 1200 })

    // 4. 后台异步同步到云函数（不阻塞 UI）
    this._backgroundSync({
      name: 'takeFromPool',
      data: {
        roomCode: this.data.roomCode,
        targetPlayerOpenId: this.data.poolTargetOpenId,
        mode: mode
      }
    })
  },

  // 自定义取分：弹出数字输入框（不走分数锁定，走 addScoreRecord）
  showCustomTake() {
    if (!this.data.isCreator) return
    if (this.data.poolScore <= 0) {
      wx.showToast({ title: '公共池没有可取的分数', icon: 'none' })
      return
    }
    const target = this.data.players.find(p => p.openId === this.data.poolTargetOpenId)
    if (!target) {
      wx.showToast({ title: '请先选择取分玩家', icon: 'none' })
      return
    }
    this.setData({
      showCustomTakeDialog: true,
      customTakeAmount: '',
      customTakeTargetName: target.nickName
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
    const targetName = this.data.customTakeTargetName
    wx.showModal({
      title: '自定义取分',
      content: `确定从公共池取 ${amount} 分给 ${targetName}？`,
      success: r => {
        if (r.confirm) {
          this._executeCustomTake(amount, targetName)
        }
      }
    })
  },

  // 自定义取分调用 addScoreRecord（type=down），不影响分数锁定
  _executeCustomTake(amount, targetName) {
    if (this.data.acting) return
    this.setData({ acting: true })

    console.log('[walk_scoring] _executeCustomTake:', { amount, targetName, targetId: this.data.poolTargetOpenId })

    // 1. 本地乐观更新 UI（即时响应）
    const local = this._applyOptimisticScore('down', amount, this.data.poolTargetOpenId)
    if (!local) {
      this.setData({ acting: false })
      wx.showToast({ title: '目标玩家不在房间中', icon: 'none' })
      return
    }

    // 2. 关闭弹窗、释放防重复锁
    this.setData({ showCustomTakeDialog: false, customTakeAmount: '', acting: false })

    // 3. 显示操作结果
    wx.showToast({ title: `取分 ${amount} → ${targetName}`, icon: 'success', duration: 1200 })

    // 4. 后台异步同步到云函数（不阻塞 UI）
    this._backgroundSync({
      name: 'addScoreRecord',
      data: {
        roomCode: this.data.roomCode,
        type: 'down',
        score: amount,
        targetPlayerOpenId: this.data.poolTargetOpenId
      }
    })
  },


  // 从房间栏给自己加底分（仅限房主）
  addBaseScoreSelf() {
    if (!this.data.isCreator) return
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

  // 给玩家增加100底分（二次确认）
  addBaseScore(e) {
    // 权限校验：仅房主可操作
    if (!this.data.isCreator) {
      wx.showToast({ title: '仅房主可操作', icon: 'none' })
      return
    }
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
