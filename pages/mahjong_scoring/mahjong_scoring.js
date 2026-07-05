/**
 * 麻将计分 — 在线多人房间模式
 *
 * 功能：
 *   1. 房间创建/加入/分享（云函数体系）
 *   2. 麻将计分：点炮胡 / 自摸胡 / 杠分
 *   3. 实时同步：watcher + 乐观更新
 *   4. 结算排名 / 对局记录 / 历史存档
 */

var STORAGE_MJ_ROOM = '__mj_room__';

// ---- 工具 ----
function nowTimeStr() {
  var d = new Date();
  var pad = function (n) { return n < 10 ? '0' + n : n; };
  return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

/** 返回完整日期时间戳：YYYY-MM-DD HH:MM:SS */
function nowDateTimeStr() {
  var d = new Date();
  var pad = function (n) { return n < 10 ? '0' + n : n; };
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

/** 补齐 4 槽位 for WXML */
function padSlots(players) {
  var slots = [];
  for (var i = 0; i < 4; i++) {
    if (i < players.length && players[i]) {
      slots.push({ hasPlayer: true, slotIndex: i, player: players[i] });
    } else {
      var isAdd = (i === players.length && players.length < 4);
      slots.push({ hasPlayer: false, slotIndex: i, isAddSlot: isAdd });
    }
  }
  return slots;
}

Page({

  data: {
    // ---- 通用 ----
    loading: true,
    myOpenId: '',
    myNickName: '',
    myAvatarUrl: '',

    // ---- 房间 ----
    roomId: '',
    roomCode: '',
    isCreator: false,

    // ---- 玩家（云模式：players 为云端数据，含 netScore） ----
    players: [],
    slots: [],

    // ---- 对局记录（云模式下为从 score_records 拉取的 mj_round 记录） ----
    rounds: [],

    // ---- 计分弹窗玩家列表 ----
    scoringPlayers: [],

    // ---- 台板开关 ----
    taiBanEnabled: false,

    // ===== 弹窗显隐 =====
    showScoring: false,
    showSettle: false,
    showJoinInput: false,
    joinRoomCode: '',

    // ===== 计分弹窗 =====
    scoringMode: 'dianpao',
    scoringWinnerIdx: -1,
    scoringLoserIdx: -1,
    scoringFanCount: 1,
    scoringBaseScore: 1,
    scoringBarScore: 0,
    scoringBarPlayerIdx: -1,
    scoringPreview: '',

    // ===== 转账 =====
    showTransfer: false,
    transferTargetOpenId: '',
    transferTargetName: '',
    transferAmount: '',

    // ===== 结算 =====
    settleRank: [],

    // ---- 无房间状态 Tab ----
    homeActiveTab: 'home',

    // ===== 记录 Tab =====
    homeRecordTab: 'active',   // 'active' | 'settled'
    records: [],               // 当前展示的记录
    allActiveRounds: [],       // 进行中 — 所有轮次
    allSettledRounds: [],      // 已结束 — 所有已结算轮次
    selectedMonth: '',         // '' = 全部
    monthPickerRange: ['全部'],
    recordsLoaded: false,
    showDeleteConfirm: false,
    deleteTarget: null,        // { recordId, roomCode }

    // ===== 留言板 =====
    showMessageBoard: false,
    messages: [],
    newMessageText: '',
    msgUnreadCount: 0,

    // ===== 清除记录确认 =====
    showCacheConfirm: false,

    // ===== 历史记录 =====
    showHistory: false,
    historyList: [],
    historyLoading: true,

  },

  // ================================================================
  // 生命周期
  // ================================================================
  onLoad: function (query) {
    wx.showShareMenu({ withShareTicket: true, menus: ['shareAppMessage', 'shareTimeline'] });
    var self = this;
    // 安全兜底：6 秒后强制结束 loading，防止卡死
    self._loadingTimer = setTimeout(function () {
      if (self.data.loading) {
        console.warn('[mahjong] 加载超时');
        self.setData({ loading: false });
      }
    }, 6000);
    this._waitReady(query);
  },

  onShow: function () {
    // 从 storage 同步最新的身份信息（支持跨页面头像/昵称互通）
    var cache = wx.getStorageSync('__my_identity__') || {};
    var updates = {};
    if (cache.nickName && cache.nickName !== this.data.myNickName) {
      updates.myNickName = cache.nickName;
    }
    if (cache.avatarUrl && cache.avatarUrl !== this.data.myAvatarUrl) {
      updates.myAvatarUrl = cache.avatarUrl;
    }
    if (Object.keys(updates).length > 0) {
      this.setData(updates);
    }
    // 页面从后台恢复时，watcher 可能已被系统回收；房间内则重建监听
    if (this.data.roomId && !this.data.loading) {
      this._startWatch();
    }
  },

  onUnload: function () {
    if (this._loadingTimer) { clearTimeout(this._loadingTimer); this._loadingTimer = null; }
    this._closeWatcher();
  },

  onShareAppMessage: function () {
    if (this.data.roomCode) {
      return {
        title: this.data.myNickName + ' 邀你加入麻将计分',
        path: '/pages/mahjong_scoring/mahjong_scoring?roomCode=' + this.data.roomCode,
        imageUrl: ''
      };
    }
    return {
      title: '麻将计分 — 来一局！',
      path: '/pages/mahjong_scoring/mahjong_scoring'
    };
  },

  // ================================================================
  // 身份同步
  // ================================================================
  _waitReady: function (query) {
    var app = getApp();
    var cache = wx.getStorageSync('__my_identity__') || {};
    // 直接同步读取：openId 已在 app.js onLaunch 中从缓存恢复，无需轮询等待
    this.setData({
      myOpenId: app.globalData.openId || cache.openId || '',
      myNickName: app.globalData.nickName || cache.nickName || '',
      myAvatarUrl: cache.avatarUrl || ''
    });
    this._afterIdentity(query);
  },

  _afterIdentity: function (query) {
    var self = this;
    // 从分享链接/加入房间进入（带 roomCode 或 roomId，统一走 joinRoom 云函数）
    if (query && (query.roomCode || query.roomId)) {
      self._doJoinRoom(query.roomCode || query.roomId);
      return;
    }
    // 清掉残留缓存，确保每次进入都先展示首页/记录/我的主界面
    // 用户可通过首页「创建房间」按钮主动进入房间模式
    wx.removeStorageSync(STORAGE_MJ_ROOM);
    wx.removeStorageSync('__mj_room_cache__');
    self.setData({ loading: false, homeActiveTab: 'home' });
  },

  // ================================================================
  // 头像 + 昵称
  // ================================================================

  onChooseAvatar: function (e) {
    var tempUrl = e.detail.avatarUrl;
    if (!tempUrl) return;
    this.setData({ myAvatarUrl: tempUrl });
    // 同步到 globalData，确保跨页面互通
    getApp().globalData.avatarUrl = tempUrl;
    var id = wx.getStorageSync('__my_identity__') || {};
    id.avatarUrl = tempUrl;
    wx.setStorageSync('__my_identity__', id);
    if (wx.cloud) {
      wx.cloud.uploadFile({
        cloudPath: 'avatars/' + this.data.myOpenId + '_' + Date.now() + '.png',
        filePath: tempUrl,
        success: function (res) {
          var ident = wx.getStorageSync('__my_identity__') || {};
          ident.avatarUrl = res.fileID;
          wx.setStorageSync('__my_identity__', ident);
        }
      });
    }
  },

  onNickNameBlur: function (e) {
    var name = (e.detail.value || '').trim();
    if (name && name !== this.data.myNickName) {
      getApp().setNickName(name);
      this.setData({ myNickName: name });
    }
  },

  // ================================================================
  // 无房间状态 — 首页 Tab 切换
  // ================================================================

  /** 切换底部 Tab（仅在无房间状态下生效） */
  onHomeTabChange: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ homeActiveTab: tab });
    // 切换到记录 Tab 时加载数据
    if (tab === 'records') {
      this._loadRecordsData();
    }
  },

  /** 首页/我的 → 创建房间 */
  onHomeCreateRoom: function () {
    this.createRoom();
  },

  /** 首页/我的 → 加入房间 */
  onHomeJoinRoom: function () {
    this.showJoinRoomInput();
  },

  // onHomeRecords 已移除 — 记录现在是同页第三个 Tab，通过 onHomeTabChange 切换

  // ================================================================
  // 导航 + 公告
  // ================================================================

  /** 点击玩家头像 → 转账 */
  onPlayerTap: function (e) {
    var openId = e.currentTarget.dataset.openid;
    var nickname = e.currentTarget.dataset.nickname;
    // 不能转给自己
    if (openId === this.data.myOpenId) {
      wx.showToast({ title: '不能转账给自己', icon: 'none' });
      return;
    }
    this.setData({
      showTransfer: true,
      transferTargetOpenId: openId,
      transferTargetName: nickname || '玩家',
      transferAmount: ''
    });
  },

  // ================================================================
  // 房间管理（云模式）
  // ================================================================

  createRoom: function () {
    var self = this;
    if (!self.data.myNickName) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '创建中...', mask: true });
    wx.cloud.callFunction({
      name: 'createRoom',
      data: {
        nickName: self.data.myNickName,
        avatarUrl: self.data.myAvatarUrl,
        gameType: 'mahjong_scoring'
      }
    }).then(function (res) {
      wx.hideLoading();
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message, icon: 'none' });
        return;
      }
      var roomId = res.result.roomId;
      var roomCode = res.result.roomCode;

      // 新房间直接构建初始状态（创建者唯一玩家，0 条对局记录），跳过 getRoomInfo 云调用
      var creator = {
        openId: self.data.myOpenId,
        nickName: self.data.myNickName,
        avatarUrl: self.data.myAvatarUrl || '',
        joinTime: Date.now(),
        baseScore: 0,
        netScore: 0,
        isMe: true
      };
      var players = [creator];
      self._sortSelfFirst(players);
      var rounds = [];

      self.setData({
        roomId: roomId,
        roomCode: roomCode,
        isCreator: true,
        loading: false,
        players: players,
        slots: padSlots(players),
        rounds: rounds
      });

      // 持久化房间信息
      wx.setStorageSync(STORAGE_MJ_ROOM, { roomId: roomId, roomCode: roomCode });
      // 写入缓存，后续进记录 Tab 及页面恢复时可用
      wx.setStorageSync('__mj_room_cache__', {
        roomCode: roomCode,
        roomId: roomId,
        isCreator: true,
        players: players,
        rounds: rounds,
        cachedAt: Date.now()
      });

      self._startWatch();
      // 后台静默拉取权威数据（loading 已为 false，_loadRoomData 走 silent 模式），
      // 确保第一时间捕获刚加入的其他玩家
      self._loadRoomData();
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: '创建失败: ' + (err.errMsg || '网络错误'), icon: 'none' });
    });
  },

  showJoinRoomInput: function () {
    this.setData({ showJoinInput: true, joinRoomCode: '' });
  },

  cancelJoinRoom: function () {
    this.setData({ showJoinInput: false, joinRoomCode: '' });
  },

  setJoinRoomCode: function (e) {
    var val = (e.detail.value || '').replace(/\\D/g, '').slice(0, 6);
    this.setData({ joinRoomCode: val });
  },

  joinRoom: function () {
    var code = this.data.joinRoomCode;
    if (!code) return;
    if (code.length !== 6) {
      wx.showToast({ title: '房间号应为6位数字', icon: 'none' });
      return;
    }
    this.setData({ showJoinInput: false, joinRoomCode: '' });
    this._doJoinRoom(code);
  },

  _doJoinRoom: function (roomCode) {
    var self = this;
    if (!self.data.myNickName) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' });
      // 无昵称 → 回退到首页选择模式
      self.setData({ loading: false, roomCode: '', roomId: '' });
      return;
    }
    // 无云环境 → 无法使用
    if (!wx.cloud) {
      wx.showToast({ title: '当前环境不支持云开发', icon: 'none' });
      self.setData({ loading: false, roomCode: '', roomId: '' });
      return;
    }
    wx.showLoading({ title: '加入中...', mask: true });
    wx.cloud.callFunction({
      name: 'joinRoom',
      data: {
        roomCode: roomCode,
        nickName: self.data.myNickName,
        avatarUrl: self.data.myAvatarUrl
      }
    }).then(function (res) {
      wx.hideLoading();
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message, icon: 'none' });
        self.setData({ loading: false, roomCode: '', roomId: '' });
        return;
      }

      if (res.result.rejoined) {
        wx.showToast({ title: '欢迎回来！数据已恢复', icon: 'none' });
      }

      // 直接使用 joinRoom 返回的完整数据构建 UI，跳过 getRoomInfo 云调用
      var roomData = res.result;
      var players = roomData.players || [];
      var records = roomData.records || [];
      var isCreator = roomData.room && roomData.room.creatorOpenId === self.data.myOpenId;

      // 标记自己
      for (var i = 0; i < players.length; i++) {
        players[i].isMe = (players[i].openId === self.data.myOpenId);
      }

      // 自己排最前面
      self._sortSelfFirst(players);

      // 从 mj_round 类型记录构建对局列表
      var rounds = [];
      for (var j = 0; j < records.length; j++) {
        var r = records[j];
        if (r.type === 'mj_round') {
          rounds.push({
            roundNum: r.roundNum,
            createTime: r.createTime,
            timeStr: r.createTime ? self._formatRecordTime(r.createTime) : '',
            mode: r.mode === 'zimo' ? '自摸' : r.mode === 'transfer' ? '转账' : '点炮',
            modeCode: r.mode,
            winnerName: r.winnerName || '',
            loserName: r.loserName || '',
            fanCount: r.fanCount || 0,
            baseScore: r.baseScore || 0,
            barScore: r.barScore || 0,
            barPlayerName: r.barPlayerName || '',
            taiBanEnabled: r.taiBanEnabled || false,
            playerDeltas: r.playerDeltas || [],
            snapshot: r.snapshot || [],
            roomCode: roomData.roomCode,
            _id: r._id
          });
        }
      }
      rounds.sort(function (a, b) { return b.roundNum - a.roundNum; });

      self.setData({
        roomId: roomData.roomId,
        roomCode: roomData.roomCode,
        isCreator: isCreator,
        loading: false,
        players: players,
        slots: padSlots(players),
        rounds: rounds
      });

      wx.setStorageSync(STORAGE_MJ_ROOM, { roomId: roomData.roomId, roomCode: roomData.roomCode });
      wx.setStorageSync('__mj_room_cache__', {
        roomCode: roomData.roomCode,
        roomId: roomData.roomId,
        isCreator: isCreator,
        players: players,
        rounds: rounds,
        cachedAt: Date.now()
      });

      self._startWatch();
      // 后台静默拉取权威数据，确保数据一致性
      self._loadRoomData();
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: '加入失败: ' + (err.errMsg || '网络错误'), icon: 'none' });
      self.setData({ loading: false, roomCode: '', roomId: '' });
    });
  },

  leaveRoom: function () {
    var self = this;
    wx.showModal({
      title: '退出房间',
      content: '退出后可重新加入，数据保留',
      success: function (r) {
        if (r.confirm) {
          // 保存最后退出的房间号（记录Tab"进行中"兜底查询用）
          if (self.data.roomCode) {
            wx.setStorageSync('__mj_last_room__', self.data.roomCode);
          }
          self._closeWatcher();
          wx.removeStorageSync(STORAGE_MJ_ROOM);
          wx.removeStorageSync('__mj_room_cache__');
          self.setData({
            roomId: '', roomCode: '', isCreator: false,
            players: [], slots: padSlots([]), rounds: [], loading: false,
            homeActiveTab: 'home'
          });
          // 回到无房间 Tab 首页
        }
      }
    });
  },

  // ================================================================
  // 加载云端房间数据
  // ================================================================
  _loadRoomData: function (callback) {
    var self = this;
    if (!self.data.roomCode) {
      if (callback) callback({ message: '无房间' }, false);
      return;
    }
    // 是否静默刷新（已展示缓存数据时 loading 为 false）
    var silent = !self.data.loading;

    wx.cloud.callFunction({
      name: 'getRoomInfo',
      data: { roomCode: self.data.roomCode }
    }).then(function (res) {
      if (!res.result.ok) {
        if (res.result.message === '房间不存在') {
          self.leaveRoom();
        } else if (!silent) {
          wx.showToast({ title: res.result.message || '加载失败', icon: 'none' });
        }
        self.setData({ loading: false });
        if (callback) callback({ message: res.result.message || '加载失败' }, false);
        return;
      }
      var players = res.result.players || [];
      var records = res.result.records || [];

      // 标记自己
      for (var i = 0; i < players.length; i++) {
        players[i].isMe = (players[i].openId === self.data.myOpenId);
      }

      // 自己排最前面
      self._sortSelfFirst(players);

      // 从 mj_round 类型的记录中提取对局
      var rounds = [];
      for (var j = 0; j < records.length; j++) {
        var r = records[j];
        if (r.type === 'mj_round') {
          rounds.push({
            roundNum: r.roundNum,
            createTime: r.createTime,           // 原始时间戳，供记录 Tab 筛选和格式化
            timeStr: r.createTime ? self._formatRecordTime(r.createTime) : '',
            mode: r.mode === 'zimo' ? '自摸' : r.mode === 'transfer' ? '转账' : '点炮',
            modeCode: r.mode,                    // 原始模式码，供记录 Tab 使用
            winnerName: r.winnerName || '',
            loserName: r.loserName || '',
            fanCount: r.fanCount || 0,
            baseScore: r.baseScore || 0,
            barScore: r.barScore || 0,
            barPlayerName: r.barPlayerName || '',
            taiBanEnabled: r.taiBanEnabled || false,
            playerDeltas: r.playerDeltas || [],
            snapshot: r.snapshot || [],
            roomCode: self.data.roomCode,        // 供记录 Tab 删除按钮使用
            _id: r._id
          });
        }
      }
      // 按局号倒序
      rounds.sort(function (a, b) { return b.roundNum - a.roundNum; });

      // 计算各玩家总分（基于云端 netScore + 对局汇总验证）
      var isCreator = res.result.room && res.result.room.creatorOpenId === self.data.myOpenId;

      // 缓存房间数据到本地，下次进入瞬时展示
      wx.setStorageSync('__mj_room_cache__', {
        roomCode: self.data.roomCode,
        roomId: self.data.roomId,
        isCreator: isCreator,
        players: players,
        rounds: rounds,
        cachedAt: Date.now()
      });

      self.setData({
        loading: false,
        isCreator: isCreator,
        players: players,
        slots: padSlots(players),
        rounds: rounds
      });
      if (callback) callback(null, true);
    }).catch(function (err) {
      console.error('加载房间数据失败:', err);
      self.setData({ loading: false });
      if (!silent) {
        wx.showToast({ title: '加载失败，请下拉刷新', icon: 'none' });
      }
      if (callback) callback(err, false);
    });
  },

  /** 手动刷新房间数据（从云端拉取最新） */
  refreshRoom: function () {
    var self = this;
    if (!self.data.roomCode) return;
    wx.showLoading({ title: '刷新中...', mask: false });
    self._loadRoomData(function (err, ok) {
      wx.hideLoading();
      if (ok) {
        wx.showToast({ title: '已刷新', icon: 'success', duration: 1200 });
      } else {
        wx.showToast({ title: '刷新云端数据失败', icon: 'none' });
      }
    });
  },

  _formatRecordTime: function (timeVal) {
    var d = typeof timeVal === 'number' ? new Date(timeVal) : new Date(timeVal);
    if (isNaN(d.getTime())) return '';
    var pad = function (n) { return n < 10 ? '0' + n : n; };
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  },

  // ================================================================
  // 实时监听
  // ================================================================
  _startWatch: function () {
    var self = this;
    if (!self.data.roomId || !wx.cloud) return;
    self._closeWatcher();
    var db = wx.cloud.database();

    // ① 监听 score_records 变化：计分/转账写入后自动刷新
    self._watcher = db.collection('score_records')
      .where({ roomId: self.data.roomId })
      .watch({
        onChange: function () {
          // 正在同步中（云函数写入后由 .then() 统一 _loadRoomData），跳过 watcher 触发的重载
          if (self._syncing > 0) return;
          self._loadRoomData();
        },
        onError: function (err) {
          console.error('score_records watch 异常:', err);
        }
      });

    // ② 监听 rooms 文档变化：玩家加入/退出时自动刷新（joinRoom 更新 rooms.players / updateTime）
    self._roomWatcher = db.collection('rooms')
      .where({ _id: self.data.roomId })
      .watch({
        onChange: function () {
          if (self._syncing > 0) return;
          self._loadRoomData();
        },
        onError: function (err) {
          console.error('rooms watch 异常:', err);
        }
      });
  },

  _closeWatcher: function () {
    if (this._watcher) {
      try { this._watcher.close(); } catch (e) { }
      this._watcher = null;
    }
    if (this._roomWatcher) {
      try { this._roomWatcher.close(); } catch (e) { }
      this._roomWatcher = null;
    }
  },

  // ================================================================
  // 对局计分（当前仅房主可用；离线下自己操作）
  // ================================================================

  onShowScoring: function () {
    if (this.data.players.length === 0) {
      wx.showToast({ title: '请先添加玩家', icon: 'none' });
      return;
    }
    // 从当前玩家列表生成计分弹窗的玩家选项
    var scoringPlayers = this.data.players.map(function (p, i) {
      return { id: i, name: p.nickName || p.name || ('玩家' + (i + 1)) };
    });
    var defaultMode = 'dianpao';
    this.setData({
      showScoring: true,
      scoringMode: defaultMode,
      scoringWinnerIdx: -1,
      scoringLoserIdx: -1,
      scoringFanCount: defaultMode === 'transfer' ? '' : 1,
      scoringBaseScore: 1,
      scoringBarScore: 0,
      scoringBarPlayerIdx: -1,
      scoringPreview: '',
      scoringPlayers: scoringPlayers
    });
  },

  onSwitchMode: function (e) {
    var mode = e.currentTarget.dataset.mode;
    this.setData({
      scoringMode: mode,
      scoringLoserIdx: mode === 'zimo' || mode === 'transfer' ? -1 : this.data.scoringLoserIdx,
      scoringFanCount: mode === 'transfer' ? '' : 1,
      scoringBaseScore: mode === 'transfer' ? 0 : 1,
      scoringBarScore: 0,
      scoringBarPlayerIdx: -1,
      scoringPreview: ''
    });
  },

  onSelectWinner: function (e) {
    var idx = parseInt(e.currentTarget.dataset.idx);
    this.setData({ scoringWinnerIdx: this.data.scoringWinnerIdx === idx ? -1 : idx, scoringPreview: '' });
    this._updateScoringPreview();
  },

  onSelectLoser: function (e) {
    var idx = parseInt(e.currentTarget.dataset.idx);
    this.setData({ scoringLoserIdx: this.data.scoringLoserIdx === idx ? -1 : idx, scoringPreview: '' });
    this._updateScoringPreview();
  },

  onSelectBarPlayer: function (e) {
    var idx = parseInt(e.currentTarget.dataset.idx);
    this.setData({ scoringBarPlayerIdx: this.data.scoringBarPlayerIdx === idx ? -1 : idx, scoringPreview: '' });
    this._updateScoringPreview();
  },

  onFanCountInput: function (e) {
    var val = parseInt(e.detail.value) || 0;
    this.setData({ scoringFanCount: Math.max(0, val), scoringPreview: '' });
    if (this.data.scoringMode !== 'transfer') {
      this._updateScoringPreview();
    }
  },

  onBaseScoreInput: function (e) {
    var val = parseInt(e.detail.value) || 0;
    this.setData({ scoringBaseScore: Math.max(0, val), scoringPreview: '' });
    this._updateScoringPreview();
  },

  onBarScoreInput: function (e) {
    var val = parseInt(e.detail.value) || 0;
    this.setData({ scoringBarScore: Math.max(0, val), scoringPreview: '' });
    this._updateScoringPreview();
  },

  _updateScoringPreview: function () {
    var d = this.data;
    var players = d.players;
    var n = players.length;
    if (n === 0) return;

    var deltas = [];
    for (var di = 0; di < n; di++) deltas[di] = 0;

    // 台板扣费
    if (d.taiBanEnabled) {
      for (var t = 0; t < n; t++) deltas[t] -= 1;
    }

    // 胡牌计分
    if (d.scoringWinnerIdx >= 0 && d.scoringFanCount > 0 && d.scoringBaseScore > 0) {
      var unit = d.scoringFanCount * d.scoringBaseScore;
      if (d.scoringMode === 'zimo') {
        deltas[d.scoringWinnerIdx] += unit * 3;
        for (var z = 0; z < n; z++) {
          if (z !== d.scoringWinnerIdx) deltas[z] -= unit;
        }
      } else {
        var l = d.scoringLoserIdx;
        if (l >= 0 && l !== d.scoringWinnerIdx) {
          deltas[d.scoringWinnerIdx] += unit;
          deltas[l] -= unit;
        }
      }
    }

    // 杠分
    if (d.scoringBarPlayerIdx >= 0 && d.scoringBarScore > 0) {
      deltas[d.scoringBarPlayerIdx] += d.scoringBarScore * 3;
      for (var b = 0; b < n; b++) {
        if (b !== d.scoringBarPlayerIdx) deltas[b] -= d.scoringBarScore;
      }
    }

    var parts = [];
    for (var k = 0; k < n; k++) {
      if (deltas[k] !== 0) {
        parts.push(players[k].nickName || players[k].name + (deltas[k] > 0 ? '+' : '') + deltas[k]);
      }
    }
    this.setData({ scoringPreview: parts.join('  ') || '无变动' });
    this._pendingDeltas = deltas;
  },

  onConfirmScoring: function () {
    var d = this.data;
    var self = this;

    // ---- 转账模式 ----
    if (d.scoringMode === 'transfer') {
      if (d.scoringWinnerIdx < 0) { wx.showToast({ title: '请选择收款玩家', icon: 'none' }); return; }
      var transferAmount = parseInt(d.scoringFanCount) || 0; // 转账模式下 fanCount 复用为金额
      if (transferAmount <= 0) { wx.showToast({ title: '请输入转账金额', icon: 'none' }); return; }
      if (d.scoringWinnerIdx === self._myPlayerIndex()) {
        wx.showToast({ title: '不能转账给自己', icon: 'none' });
        return;
      }

      var tDeltas = [];
      for (var ti = 0; ti < d.players.length; ti++) tDeltas[ti] = 0;
      tDeltas[self._myPlayerIndex()] = -transferAmount;
      tDeltas[d.scoringWinnerIdx] = transferAmount;

      var tPlayerDeltas = d.players.map(function (p, i) {
        return { name: p.nickName || p.name, openId: p.openId, delta: tDeltas[i] };
      });
      var tSnapshot = d.players.map(function (p) {
        return { openId: p.openId || p.id, totalScore: p.netScore || p.totalScore };
      });

      self._applyOptimisticMjRound(tDeltas, {
        isTransfer: true,
        transferTargetName: d.players[d.scoringWinnerIdx].nickName || d.players[d.scoringWinnerIdx].name,
        transferAmount: transferAmount
      });

      self._syncing = (self._syncing || 0) + 1; // 阻塞 watcher，防止竞态覆盖乐观更新
      wx.cloud.callFunction({
        name: 'mjAddRound',
        data: {
          roomCode: d.roomCode,
          roundNum: d.rounds.length + 1,
          mode: 'transfer',
          winnerName: d.players[d.scoringWinnerIdx].nickName || d.players[d.scoringWinnerIdx].name,
          loserName: self.data.myNickName,
          fanCount: transferAmount,
          baseScore: 0,
          barScore: 0,
          barPlayerName: '',
          taiBanEnabled: false,
          playerDeltas: tPlayerDeltas,
          snapshot: tSnapshot
        }
      }).then(function (res) {
        if (res.result && !res.result.ok) {
          wx.showToast({ title: res.result.message || '转账失败', icon: 'none' });
        }
        self._loadRoomData(function () {
          self._syncing = Math.max(0, (self._syncing || 1) - 1);
        });
      }).catch(function () {
        wx.showToast({ title: '网络异常，转账失败', icon: 'none' });
        self._loadRoomData(function () {
          self._syncing = Math.max(0, (self._syncing || 1) - 1);
        });
      });

      self.setData({ showScoring: false });
      return;
    }

    // ---- 点炮/自摸模式 ----
    if (d.scoringWinnerIdx < 0) { wx.showToast({ title: '请选择胡牌玩家', icon: 'none' }); return; }
    if (d.scoringMode === 'dianpao' && d.scoringLoserIdx < 0) { wx.showToast({ title: '点炮模式请选择点炮玩家', icon: 'none' }); return; }
    if (d.scoringFanCount <= 0 || d.scoringBaseScore <= 0) { wx.showToast({ title: '请输入番数和底分', icon: 'none' }); return; }

    var deltas = this._pendingDeltas || [];
    if (deltas.length === 0) {
      for (var di2 = 0; di2 < d.players.length; di2++) deltas[di2] = 0;
    }

    // 快照
    var snapshot = d.players.map(function (p) {
      return { openId: p.openId || p.id, totalScore: p.netScore || p.totalScore };
    });

    // 通过 mjAddRound 云函数提交
    var playerDeltas = d.players.map(function (p, i) {
      return { name: p.nickName || p.name, openId: p.openId, delta: deltas[i] };
    });

    // 先本地乐观更新
    self._applyOptimisticMjRound(deltas);

    self._syncing = (self._syncing || 0) + 1; // 阻塞 watcher，防止竞态覆盖乐观更新
    wx.cloud.callFunction({
      name: 'mjAddRound',
      data: {
        roomCode: d.roomCode,
        roundNum: d.rounds.length + 1,
        mode: d.scoringMode,
        winnerName: d.scoringWinnerIdx >= 0 ? (d.players[d.scoringWinnerIdx].nickName || d.players[d.scoringWinnerIdx].name) : '',
        loserName: d.scoringMode === 'dianpao' && d.scoringLoserIdx >= 0 ? (d.players[d.scoringLoserIdx].nickName || d.players[d.scoringLoserIdx].name) : '',
        fanCount: d.scoringFanCount,
        baseScore: d.scoringBaseScore,
        barScore: d.scoringBarScore,
        barPlayerName: d.scoringBarPlayerIdx >= 0 ? (d.players[d.scoringBarPlayerIdx].nickName || d.players[d.scoringBarPlayerIdx].name) : '',
        taiBanEnabled: d.taiBanEnabled,
        playerDeltas: playerDeltas,
        snapshot: snapshot
      }
    }).then(function (res) {
      if (res.result && !res.result.ok) {
        wx.showToast({ title: res.result.message || '计分失败', icon: 'none' });
      }
      self._loadRoomData(function () {
        self._syncing = Math.max(0, (self._syncing || 1) - 1);
      });
    }).catch(function () {
      wx.showToast({ title: '网络异常，计分失败', icon: 'none' });
      self._loadRoomData(function () {
        self._syncing = Math.max(0, (self._syncing || 1) - 1);
      });
    });

    self.setData({ showScoring: false });
  },

  /**
   * 乐观更新玩家分数 + 插入对局记录
   * @param {number[]} deltas 每个玩家的分数变动
   * @param {object}  [opts]  覆盖字段（转账模式使用）
   */
  _applyOptimisticMjRound: function (deltas, opts) {
    opts = opts || {};
    var players = this.data.players;
    var newPlayers = players.map(function (p, i) {
      return {
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl,
        baseScore: p.baseScore,
        netScore: (p.netScore || 0) + (deltas[i] || 0),
        joinTime: p.joinTime,
        isMe: p.isMe
      };
    });

    var isTransfer = opts.isTransfer || this.data.scoringMode === 'transfer';

    var round = {
      roundNum: this.data.rounds.length + 1,
      timeStr: nowTimeStr(),
      timestamp: nowDateTimeStr(),
      mode: isTransfer ? '转账' : (this.data.scoringMode === 'zimo' ? '自摸' : '点炮'),
      winnerName: isTransfer ? (opts.transferTargetName || '') : (this.data.scoringWinnerIdx >= 0 ? (players[this.data.scoringWinnerIdx].nickName || '') : ''),
      loserName: isTransfer ? (this.data.myNickName || '') : (this.data.scoringMode === 'dianpao' && this.data.scoringLoserIdx >= 0 ? (players[this.data.scoringLoserIdx].nickName || '') : ''),
      fanCount: isTransfer ? (opts.transferAmount || 0) : this.data.scoringFanCount,
      baseScore: isTransfer ? 0 : this.data.scoringBaseScore,
      barScore: isTransfer ? 0 : this.data.scoringBarScore,
      barPlayerName: isTransfer ? '' : (this.data.scoringBarPlayerIdx >= 0 ? (players[this.data.scoringBarPlayerIdx].nickName || '') : ''),
      playerDeltas: deltas.map(function (delta, i) {
        return { name: players[i].nickName || '', delta: delta };
      })
    };

    var newRounds = [round].concat(this.data.rounds);

    this.setData({
      players: newPlayers,
      slots: padSlots(newPlayers),
      rounds: newRounds
    });
  },

  onCancelScoring: function () {
    this.setData({ showScoring: false });
  },

  // ================================================================
  // 转账
  // ================================================================

  /** 将自己的头像排到玩家列表最前面 */
  _sortSelfFirst: function (players) {
    var myOpenId = this.data.myOpenId;
    for (var i = 0; i < players.length; i++) {
      if (players[i].openId === myOpenId && i !== 0) {
        var me = players.splice(i, 1)[0];
        players.unshift(me);
        break;
      }
    }
    return players;
  },

  /** 获取当前用户在 players 数组中的下标 */
  _myPlayerIndex: function () {
    var players = this.data.players;
    var myOpenId = this.data.myOpenId;
    for (var i = 0; i < players.length; i++) {
      if (players[i].openId === myOpenId) return i;
    }
    return -1;
  },

  /** 转账弹窗 — 数字键盘按键（1-9, 0, 00） */
  onKpadTap: function (e) {
    var key = e.currentTarget.dataset.key; // '1'-'9', '0', '00'
    var cur = this.data.transferAmount || '';
    // 限制最多 8 位数
    if (cur.replace(/\D/g, '').length >= 8) return;
    // 首位不能是多个 0
    if (cur === '0' && key !== '00') {
      cur = '';
    }
    var next = cur + key;
    this.setData({ transferAmount: next });
  },

  /** 转账弹窗 — 退格键 */
  onKpadDelete: function () {
    var cur = this.data.transferAmount || '';
    if (cur.length <= 1) {
      this.setData({ transferAmount: '' });
      return;
    }
    this.setData({ transferAmount: cur.slice(0, -1) });
  },

  /** 转账弹窗 — 取消 */
  onCancelTransfer: function () {
    this.setData({ showTransfer: false, transferTargetOpenId: '', transferTargetName: '', transferAmount: '' });
  },

  /** 转账弹窗 — 确认（从头像点击进入） */
  onConfirmTransfer: function () {
    var self = this;
    var d = self.data;
    var amount = parseInt(d.transferAmount) || 0;
    if (amount <= 0) {
      wx.showToast({ title: '请输入有效的转账金额', icon: 'none' });
      return;
    }
    var players = d.players;
    var myIdx = self._myPlayerIndex();
    var targetIdx = -1;
    for (var i = 0; i < players.length; i++) {
      if (players[i].openId === d.transferTargetOpenId) { targetIdx = i; break; }
    }
    if (myIdx < 0 || targetIdx < 0) {
      wx.showToast({ title: '玩家数据异常', icon: 'none' });
      return;
    }

    // 计算 deltas
    var deltas = [];
    for (var j = 0; j < players.length; j++) deltas[j] = 0;
    deltas[myIdx] = -amount;
    deltas[targetIdx] = amount;

    var playerDeltas = players.map(function (p, k) {
      return { name: p.nickName || p.name, openId: p.openId, delta: deltas[k] };
    });
    var snapshot = players.map(function (p) {
      return { openId: p.openId || p.id, totalScore: p.netScore || p.totalScore };
    });

    self._applyOptimisticMjRound(deltas, {
      isTransfer: true,
      transferTargetName: d.transferTargetName,
      transferAmount: amount
    });

    self._syncing = (self._syncing || 0) + 1; // 阻塞 watcher，防止竞态覆盖乐观更新
    wx.cloud.callFunction({
      name: 'mjAddRound',
      data: {
        roomCode: d.roomCode,
        roundNum: d.rounds.length + 1,
        mode: 'transfer',
        winnerName: d.transferTargetName,
        loserName: self.data.myNickName,
        fanCount: amount,
        baseScore: 0,
        barScore: 0,
        barPlayerName: '',
        taiBanEnabled: false,
        playerDeltas: playerDeltas,
        snapshot: snapshot
      }
    }).then(function (res) {
      if (res.result && !res.result.ok) {
        wx.showToast({ title: res.result.message || '转账失败', icon: 'none' });
      }
      self._loadRoomData(function () {
        self._syncing = Math.max(0, (self._syncing || 1) - 1);
      });
    }).catch(function () {
      wx.showToast({ title: '网络异常，转账失败', icon: 'none' });
      self._loadRoomData(function () {
        self._syncing = Math.max(0, (self._syncing || 1) - 1);
      });
    });

    self.setData({ showTransfer: false, transferTargetOpenId: '', transferTargetName: '', transferAmount: '' });
  },

  // ================================================================
  // 台板开关
  // ================================================================
  onToggleTaiBan: function (e) {
    var val = e.detail.value;
    this.setData({ taiBanEnabled: val });
  },

  // ================================================================
  // 结算
  // ================================================================
  onShowSettle: function () {
    var self = this;
    if (self.data.rounds.length === 0) {
      wx.showToast({ title: '暂无对局记录', icon: 'none' });
      return;
    }
    var sorted = self.data.players.slice().sort(function (a, b) {
      return (b.netScore || b.totalScore || 0) - (a.netScore || a.totalScore || 0);
    });
    self.setData({ showSettle: true, settleRank: sorted });
  },

  onCancelSettle: function () {
    this.setData({ showSettle: false });
  },

  // 撤销上一局
  onUndoLastRound: function () {
    wx.showToast({ title: '云模式暂不支持撤销，请手动操作', icon: 'none' });
  },


  // ================================================================
  // 页面其他
  // ================================================================

  // 分享
  onShareTimeline: function () {
    return { title: '麻将计分 — 来一局！' };
  },

  /** 在线模式切换到离线计分弹窗 */
  onLocalScoring: function () {
    this.onShowScoring();
  },

  /** 结算并清零分数（留在房间内） */
  confirmSettle: function () {
    var self = this;
    var roomCode = self.data.roomCode;
    self.setData({ showSettle: false });

    if (!roomCode) {
      wx.showToast({ title: '无房间信息', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '结算中...', mask: true });

    // 尝试调用云函数：保存结算快照 + 重置所有玩家分数为 0
    var doLocalFallback = function () {
      // 本地兜底：保存到 storage（云函数未部署时的降级方案）
      var history = wx.getStorageSync('__mj_history__') || [];
      history.unshift({
        roomCode: roomCode,
        settleTime: nowDateTimeStr(),
        gameType: 'mahjong',
        players: self.data.players.map(function (p) {
          return { nickName: p.nickName, avatarUrl: p.avatarUrl, netScore: p.netScore };
        }),
        rounds: self.data.rounds || []
      });
      if (history.length > 50) history = history.slice(0, 50);
      wx.setStorageSync('__mj_history__', history);

      // 新结算数据写入 → 清除"已清除"标记，恢复云端同步
      wx.removeStorageSync('__mj_data_cleared__');

      // 结算后本地积分清零
      var zeroPlayers = self.data.players.map(function (p) {
        p.netScore = 0;
        return p;
      });
      self.setData({ players: zeroPlayers, rounds: [] });

      // 结算完成，清除退出房间兜底标记
      wx.removeStorageSync('__mj_last_room__');

      // 更新缓存为清零状态（保持房间不退出，让用户看到清零分数）
      var settleCache = wx.getStorageSync('__mj_room_cache__');
      if (settleCache && settleCache.roomCode === roomCode) {
        settleCache.players = zeroPlayers;
        settleCache.rounds = [];
        wx.setStorageSync('__mj_room_cache__', settleCache);
      }
      var settleRoom = wx.getStorageSync(STORAGE_MJ_ROOM);
      if (settleRoom && settleRoom.roomCode === roomCode) {
        settleRoom.players = zeroPlayers;
        wx.setStorageSync(STORAGE_MJ_ROOM, settleRoom);
      }

      // 留在房间内，不清除 roomCode，用户可见清零分数
      wx.showToast({ title: '已结算，分数已清零', icon: 'success' });
      // 结算后重启 watcher，确保后续计分/加人实时同步
      self._startWatch();
    };

    if (!wx.cloud) {
      wx.hideLoading();
      doLocalFallback();
      return;
    }

    wx.cloud.callFunction({
      name: 'mjSettle',
      data: { roomCode: roomCode }
    }).then(function (res) {
      wx.hideLoading();
      if (res.result && res.result.ok) {
        // 云结算成功，同步保存本地历史（确保记录Tab有数据可展示）
        var history = wx.getStorageSync('__mj_history__') || [];
        history.unshift({
          roomCode: roomCode,
          settleTime: nowDateTimeStr(),
          gameType: 'mahjong',
          players: self.data.players.map(function (p) {
            return { nickName: p.nickName, avatarUrl: p.avatarUrl, netScore: p.netScore };
          }),
          rounds: self.data.rounds || []
        });
        if (history.length > 50) history = history.slice(0, 50);
        wx.setStorageSync('__mj_history__', history);

        // 新结算数据写入 → 清除"已清除"标记，恢复云端同步
        wx.removeStorageSync('__mj_data_cleared__');

        // 结算后本地积分清零
        var zeroPlayers = self.data.players.map(function (p) {
          p.netScore = 0;
          return p;
        });
        self.setData({ players: zeroPlayers, rounds: [] });

        // 结算完成，清除退出房间兜底标记 + 更新本地缓存为零
        wx.removeStorageSync('__mj_last_room__');

        // 更新缓存为清零状态（保持房间不退出，让用户看到清零分数）
        var settleCache2 = wx.getStorageSync('__mj_room_cache__');
        if (settleCache2 && settleCache2.roomCode === roomCode) {
          settleCache2.players = zeroPlayers;
          settleCache2.rounds = [];
          wx.setStorageSync('__mj_room_cache__', settleCache2);
        }
        var settleRoom2 = wx.getStorageSync(STORAGE_MJ_ROOM);
        if (settleRoom2 && settleRoom2.roomCode === roomCode) {
          settleRoom2.players = zeroPlayers;
          wx.setStorageSync(STORAGE_MJ_ROOM, settleRoom2);
        }

        // 留在房间内，不清除 roomCode，用户可见清零分数
        wx.showToast({ title: '已结算，分数已清零', icon: 'success' });
        // 结算后重启 watcher：mjSettle 清空了全部 score_records，
        // watcher 跟踪空数据集可能静默失效，重建确保后续计分/加人实时同步
        self._startWatch();
        self._loadHistory();
      } else {
        // 云函数返回失败（如未部署），降级到本地
        wx.hideLoading();
        console.warn('[mjSettle] 云端失败，降级本地:', res.result);
        doLocalFallback();
      }
    }).catch(function (err) {
      wx.hideLoading();
      console.warn('[mjSettle] 调用失败，降级本地:', err);
      doLocalFallback();
    });
  },

  /** 退出房间的通用清理逻辑 */
  _doExitRoom: function () {
    this._closeWatcher();
    wx.removeStorageSync(STORAGE_MJ_ROOM);
    wx.removeStorageSync('__mj_room_cache__');
    this.setData({
      roomId: '', roomCode: '', isCreator: false,
      players: [], slots: padSlots([]), rounds: [], loading: false,
      homeActiveTab: 'home'
    });
  },

  // 阻止冒泡
  _preventBubble: function () {},

  // ================================================================
  // 我的 Tab — 功能入口
  // ================================================================

  /** 修改个人资料：弹出选项（更换头像 / 修改昵称） */
  onProfileEdit: function () {
    var self = this;
    wx.showActionSheet({
      itemList: ['更换头像', '修改昵称'],
      success: function (res) {
        if (res.tapIndex === 0) {
          // 更换头像 — 触发 chooseAvatar 流程（通过 mine-avatar-btn 已支持，此处二次确认引导）
          wx.showToast({ title: '点击头像即可更换', icon: 'none' });
        } else if (res.tapIndex === 1) {
          // 修改昵称 — 弹出输入框
          wx.showModal({
            title: '修改昵称',
            editable: true,
            placeholderText: '请输入新昵称',
            content: self.data.myNickName || '',
            success: function (modalRes) {
              if (modalRes.confirm && modalRes.content) {
                var name = modalRes.content.trim();
                if (name) {
                  getApp().setNickName(name);
                  self.setData({ myNickName: name });
                  wx.showToast({ title: '昵称已更新', icon: 'success' });
                }
              }
            }
          });
        }
      }
    });
  },

  /** 个人数据 → 麻将个人统计页面 */
  onPersonalData: function () {
    wx.navigateTo({ url: '/pages/mj_statistics/mj_statistics' });
  },

  /** 优化建议 — 写入 app_messages 云集合 + 本地存储，与首页留言板互通 */
  onFeedback: function () {
    var self = this;
    wx.showModal({
      title: '优化建议',
      editable: true,
      placeholderText: '请输入您的建议或反馈...',
      content: '',
      confirmText: '提交',
      success: function (res) {
        if (res.confirm && res.content) {
          var content = res.content.trim();
          if (!content) return;
          var nickName = self.data.myNickName || '匿名用户';
          var avatarUrl = self.data.myAvatarUrl || '';
          var localId = 'f_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
          var msg = {
            id: localId,
            nickName: nickName,
            avatarUrl: avatarUrl,
            content: content,
            timeStr: '刚刚',
            timeFull: new Date().toISOString()
          };
          // 1. 写入本地存储（与首页留言板共享 __app_messages__ key）
          var messages = wx.getStorageSync('__app_messages__') || [];
          messages.unshift(msg);
          if (messages.length > 200) messages = messages.slice(0, 200);
          wx.setStorageSync('__app_messages__', messages);
          // 2. 通过云函数同步到云端（其他玩家可见）
          if (wx.cloud) {
            wx.cloud.callFunction({
              name: 'messageBoard',
              data: { action: 'add', localId: localId, nickName: nickName, avatarUrl: avatarUrl, content: content }
            }).catch(function (err) {
              console.error('[留言板] 云端同步失败:', err.errMsg || err)
            });
          }
          wx.showToast({ title: '感谢您的反馈！', icon: 'success' });
        }
      }
    });
  },

  /** 清除记录 — 弹出确认框 */
  onClearCache: function () {
    this.setData({ showCacheConfirm: true });
  },

  /** 确认清除记录 */
  confirmClearCache: function () {
    var self = this;
    wx.showLoading({ title: '清除中...' });
    // 1. 先调用云函数清除云端数据库记录（避免下次拉取又回灌）
    wx.cloud.callFunction({
      name: 'mjClearHistory',
      data: {}
    }).then(function (res) {
      if (res.result && res.result.ok) {
        console.log('[clear] 云端已清除 ' + (res.result.deletedCount || 0) + ' 条结算记录');
      } else {
        console.warn('[clear] 云端返回失败:', res.result);
        wx.setStorageSync('__mj_data_cleared__', true);
      }
    }).catch(function (err) {
      // 云函数调用失败 → 设标记兜底，防止下次云端数据回灌
      console.warn('[clear] 云端清除失败，启用本地标记兜底:', err);
      wx.setStorageSync('__mj_data_cleared__', true);
    }).then(function () {
      // 2. 无论云端成功与否，清除本地存储
      wx.removeStorageSync('__mj_room__');
      wx.removeStorageSync('__mj_room_cache__');
      wx.removeStorageSync('__mj_last_room__');
      wx.removeStorageSync('__mj_history__');
      wx.removeStorageSync('__my_identity__');
      // 3. 同步清空页面展示数据（含个人数据）
      self.setData({
        showCacheConfirm: false,
        allActiveRounds: [],
        allSettledRounds: [],
        historyList: [],
        recordsLoaded: false,
        myNickName: '',
        myAvatarUrl: ''
      });
      self._applyRecordsFilter();
      wx.hideLoading();
      wx.showToast({ title: '记录已清除', icon: 'success' });
    });
  },

  /** 取消清除记录 */
  cancelClearCache: function () {
    this.setData({ showCacheConfirm: false });
  },

  // ================================================================
  // 记录 Tab — 进行中 / 已结束
  // ================================================================

  /** 提取 YYYY-MM */
  _recToMonth: function (ts) {
    if (!ts) return '';
    var d = new Date(ts);
    var pad = function (n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1);
  },

  /** 在玩家列表中按名字查找 */
  _findPlayerInList: function (players, name) {
    if (!players || !name) return null;
    for (var i = 0; i < players.length; i++) {
      if (players[i].nickName === name) return players[i];
    }
    return null;
  },

  /** 加载记录数据（进行中 + 已结束） */
  _loadRecordsData: function () {
    this._loadSettledHistoryForRecords();
    this._loadActiveRoundsForRecords();
    this.setData({ recordsLoaded: true });
  },

  /** 加载当前活跃房间的对局记录（本地优先 → 云端校验） */
  _loadActiveRoundsForRecords: function () {
    var self = this;
    var saved = wx.getStorageSync('__mj_room__');

    /** 从缓存对象构建房间摘要卡片（聚合所有轮次玩家净得分） */
    var buildRoomSummaryFromCache = function (cache) {
      var cachedPlayers = cache.players || [];
      // 汇总每个玩家在所有轮次中的净得分
      var netScoreMap = {};
      cachedPlayers.forEach(function (p) {
        var key = p.nickName || p.openId || '';
        if (key) netScoreMap[key] = 0;
      });
      (cache.rounds || []).forEach(function (round) {
        (round.playerDeltas || []).forEach(function (d) {
          var key = d.name || '';
          if (netScoreMap.hasOwnProperty(key)) {
            netScoreMap[key] += (d.delta || 0);
          }
        });
      });
      var deltas = cachedPlayers.map(function (p) {
        var key = p.nickName || p.openId || '';
        return {
          name: p.nickName || '',
          delta: netScoreMap[key] || 0,
          avatarUrl: p.avatarUrl || ''
        };
      });
      return {
        _id: 'active_' + (cache.roomCode || ''),
        isActive: true,
        roomCode: cache.roomCode || '',
        playerDeltas: deltas,
        createTime: cache.createTime || Date.now(),
        players: cachedPlayers,
        _fromCloud: false
      };
    };

    /** 从云端 getRoomInfo 结果构建房间摘要（players 已含 netScore） */
    var buildRoomSummaryFromCloud = function (roomCode, players) {
      var deltas = (players || []).map(function (p) {
        return {
          name: p.nickName || '',
          delta: p.netScore || 0,
          avatarUrl: p.avatarUrl || ''
        };
      });
      return {
        _id: 'active_' + roomCode,
        isActive: true,
        roomCode: roomCode,
        playerDeltas: deltas,
        createTime: Date.now(),
        players: players || [],
        _fromCloud: false
      };
    };

    if (!saved || !saved.roomCode) {
      // 第一层兜底：__mj_room_cache__（跨页面可能保留的残留数据）
      var fallbackCache = wx.getStorageSync('__mj_room_cache__');
      if (fallbackCache && fallbackCache.rounds && fallbackCache.rounds.length > 0) {
        var summary = buildRoomSummaryFromCache(fallbackCache);
        self.setData({ allActiveRounds: [summary] });
        self._applyRecordsFilter();
        return;
      }
      // 第二层兜底：__mj_last_room__（退出未结算的房间号）→ 云端查询
      var lastRoomCode = wx.getStorageSync('__mj_last_room__');
      if (lastRoomCode && wx.cloud) {
        wx.cloud.callFunction({
          name: 'getRoomInfo',
          data: { roomCode: lastRoomCode }
        }).then(function (res) {
          if (!res.result.ok) {
            // 房间已不存在或已结算 → 清除兜底标记
            wx.removeStorageSync('__mj_last_room__');
            self.setData({ allActiveRounds: [] });
            self._applyRecordsFilter();
            return;
          }
          var records = (res.result.records || []);
          var players = res.result.players || [];
          var rounds = records.filter(function (r) { return r.type === 'mj_round'; });
          // 无活跃记录 → 房间可能已结算，清除兜底标记
          if (rounds.length === 0) {
            wx.removeStorageSync('__mj_last_room__');
            self.setData({ allActiveRounds: [] });
            self._applyRecordsFilter();
            return;
          }
          var summary = buildRoomSummaryFromCloud(lastRoomCode, players);
          self.setData({ allActiveRounds: [summary] });
          self._applyRecordsFilter();
        }).catch(function () {
          self.setData({ allActiveRounds: [] });
          self._applyRecordsFilter();
        });
        return;
      }
      // 三层兜底都无数据
      self.setData({ allActiveRounds: [] });
      self._applyRecordsFilter();
      return;
    }

    // 本地优先：从缓存瞬时展示，后台云端刷新
    var cache = wx.getStorageSync('__mj_room_cache__');
    if (cache && cache.roomCode === saved.roomCode && cache.rounds && cache.rounds.length > 0) {
      var cacheSummary = buildRoomSummaryFromCache(cache);
      self.setData({ allActiveRounds: [cacheSummary] });
      self._applyRecordsFilter();
    }

    // 无云环境 → 仅展示缓存
    if (!wx.cloud) {
      if (!self.data.allActiveRounds.length) {
        self.setData({ allActiveRounds: [] });
        self._applyRecordsFilter();
      }
      return;
    }

    // 后台拉取云端权威数据
    wx.cloud.callFunction({
      name: 'getRoomInfo',
      data: { roomCode: saved.roomCode }
    }).then(function (res) {
      if (!res.result.ok) {
        // 已有缓存数据则保留，不清空
        if (!self.data.allActiveRounds.length) {
          self.setData({ allActiveRounds: [] });
          self._applyRecordsFilter();
        }
        return;
      }
      var players = res.result.players || [];
      var cloudSummary = buildRoomSummaryFromCloud(saved.roomCode, players);
      self.setData({ allActiveRounds: [cloudSummary] });
      self._applyRecordsFilter();
    }).catch(function () {
      // 已有缓存数据则保留，不清空
      if (!self.data.allActiveRounds.length) {
        self.setData({ allActiveRounds: [] });
        self._applyRecordsFilter();
      }
    });
  },

  /** 加载已结算历史（本地优先 → 云端补充）
   *  与历史弹窗保持一致：每个房间一条结算摘要卡片 */
  _loadSettledHistoryForRecords: function () {
    var self = this;

    // 第一步：从本地 __mj_history__ 加载（每个房间一条结算卡片）
    var history = wx.getStorageSync('__mj_history__') || [];
    var localRoomCodes = {};
    var settledCards = [];

    history.forEach(function (room) {
      localRoomCodes[room.roomCode] = true;
      var roomPlayers = room.players || [];

      // 将玩家 netScore 转为 playerDeltas（与历史弹窗格式一致）
      var deltas = roomPlayers.map(function (p) {
        return {
          name: p.nickName || '',
          delta: p.netScore || 0,
          avatarUrl: p.avatarUrl || ''
        };
      });

      settledCards.push({
        _id: 'local_' + room.roomCode,
        isActive: false,
        mode: '结算',
        winnerName: '',
        loserName: '',
        fanCount: 0,
        baseScore: 0,
        barScore: 0,
        barPlayerName: '',
        playerDeltas: deltas,
        createTime: room.settleTime || 0,
        roomCode: room.roomCode,
        settleTime: room.settleTime || 0,
        players: roomPlayers,
        _fromCloud: false
      });
    });

    settledCards.sort(function (a, b) { return (b.createTime || 0) - (a.createTime || 0); });
    self.setData({ allSettledRounds: settledCards });
    self._applyRecordsFilter();

    // 第二步：云端拉取 mj_settlements（补充本地没有的结算记录）
    if (!wx.cloud) return;

    // 用户已清除记录 → 跳过云端拉取，避免数据回灌
    if (wx.getStorageSync('__mj_data_cleared__')) return;

    wx.cloud.callFunction({
      name: 'getMjHistory',
      data: {}
    }).then(function (res) {
      if (!res.result || !res.result.ok || !res.result.history) return;

      var cloudSettlements = res.result.history;
      var merged = self.data.allSettledRounds.slice();

      cloudSettlements.forEach(function (settlement) {
        // 本地已有该房间 → 跳过（本地数据优先）
        if (localRoomCodes[settlement.roomCode]) return;

        // 云端结算 → 一条摘要记录（与历史弹窗格式一致）
        var deltas = (settlement.players || []).map(function (p) {
          return {
            name: p.nickName || '',
            delta: p.netScore || 0,
            avatarUrl: p.avatarUrl || ''
          };
        });

        merged.push({
          _id: settlement._id || ('cloud_' + settlement.roomCode),
          isActive: false,
          mode: '结算',
          winnerName: '',
          loserName: '',
          fanCount: 0,
          baseScore: 0,
          barScore: 0,
          barPlayerName: '',
          playerDeltas: deltas,
          createTime: settlement.settleTime || 0,
          roomCode: settlement.roomCode,
          settleTime: settlement.settleTime || 0,
          players: settlement.players || [],
          _fromCloud: true
        });
      });

      merged.sort(function (a, b) { return (b.createTime || 0) - (a.createTime || 0); });
      self.setData({ allSettledRounds: merged });
      self._applyRecordsFilter();
    }).catch(function (err) {
      console.warn('[记录Tab] getMjHistory 云端拉取失败:', err);
    });
  },

  /** 应用 Tab + 月份筛选 */
  _applyRecordsFilter: function () {
    var isActive = this.data.homeRecordTab === 'active';
    var source = isActive ? this.data.allActiveRounds : this.data.allSettledRounds;
    var month = this.data.selectedMonth;
    var self = this;

    var filtered = source;
    if (month) {
      filtered = source.filter(function (r) {
        return self._recToMonth(r.createTime) === month;
      });
    }

    // 提取可用月份
    var monthsSet = {};
    source.forEach(function (r) {
      var m = self._recToMonth(r.createTime);
      if (m) monthsSet[m] = true;
    });
    var months = Object.keys(monthsSet).sort().reverse();

    this.setData({
      records: filtered,
      monthPickerRange: ['全部'].concat(months)
    });
  },

  /** 记录子 Tab 切换（进行中 / 已结束） */
  onHomeRecordTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ homeRecordTab: tab, selectedMonth: '' });
    this._applyRecordsFilter();
  },

  /** 月份筛选 picker */
  onMonthPickerChange: function (e) {
    var index = e.detail.value;
    var range = this.data.monthPickerRange;
    var month = index === 0 ? '' : range[index];
    this.setData({ selectedMonth: month });
    this._applyRecordsFilter();
  },

  /** 点击进行中房间卡片 → 进入房间 */
  onEnterActiveRoom: function (e) {
    var ds = e.currentTarget.dataset;
    // 仅进行中卡片可点击进入
    if (!ds.active || ds.active === 'false') return;
    var roomCode = ds.room;
    if (!roomCode) return;

    // 已在房间内（__mj_room__ 匹配）→ 切回首页 Tab
    var saved = wx.getStorageSync('__mj_room__');
    if (saved && saved.roomCode === roomCode) {
      this.setData({ homeActiveTab: 'home' });
      return;
    }

    // 重新加入房间
    this._doJoinRoom(roomCode);
  },

  /** 删除记录按钮 */
  onDeleteRound: function (e) {
    var recordId = e.currentTarget.dataset.id;
    var roomCode = e.currentTarget.dataset.room;
    this.setData({
      showDeleteConfirm: true,
      deleteTarget: { recordId: recordId, roomCode: roomCode }
    });
  },

  /** 确认删除 */
  confirmDelete: function () {
    var self = this;
    var target = self.data.deleteTarget;
    if (!target) return;

    // 本地存储的结算卡片（_id 以 'local_' 开头）→ 直接从本地移除，无需调云函数
    var isLocalEntry = target.recordId && target.recordId.indexOf('local_') === 0;
    if (isLocalEntry) {
      wx.showLoading({ title: '删除中...' });
      // 从 __mj_history__ 中移除对应房间
      var roomCode = target.roomCode;
      var history = wx.getStorageSync('__mj_history__') || [];
      history = history.filter(function (room) { return room.roomCode !== roomCode; });
      wx.setStorageSync('__mj_history__', history);
      // 从列表中移除（本地条目用 roomCode 精确匹配）
      var filtered = self.data.allSettledRounds.filter(function (r) {
        return r.roomCode !== roomCode;
      });
      self.setData({ allSettledRounds: filtered });
      wx.hideLoading();
      self.setData({ showDeleteConfirm: false, deleteTarget: null });
      self._applyRecordsFilter();
      wx.showToast({ title: '已删除', icon: 'success' });
      return;
    }

    // 云端记录 → 调用云函数删除
    wx.showLoading({ title: '删除中...' });
    wx.cloud.callFunction({
      name: 'deleteMjRound',
      data: { recordId: target.recordId, roomCode: target.roomCode }
    }).then(function (res) {
      wx.hideLoading();
      if (!res.result.ok) {
        wx.showToast({ title: res.result.message || '删除失败', icon: 'none' });
        return;
      }
      // 从本地列表中移除
      var isActive = self.data.homeRecordTab === 'active';
      if (isActive) {
        var activeRounds = self.data.allActiveRounds.filter(function (r) {
          return r._id !== target.recordId;
        });
        self.setData({ allActiveRounds: activeRounds });
      } else {
        var settledRounds2 = self.data.allSettledRounds.filter(function (r) {
          return r._id !== target.recordId;
        });
        self.setData({ allSettledRounds: settledRounds2 });
        self._syncHistoryDelete(target.recordId);
      }
      self.setData({ showDeleteConfirm: false, deleteTarget: null });
      self._applyRecordsFilter();
      wx.showToast({ title: '已删除', icon: 'success' });
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: '删除失败: ' + (err.errMsg || '网络错误'), icon: 'none' });
    });
  },

  /** 取消删除 */
  cancelDelete: function () {
    this.setData({ showDeleteConfirm: false, deleteTarget: null });
  },

  /** 同步删除到本地历史存储 */
  _syncHistoryDelete: function (recordId) {
    var history = wx.getStorageSync('__mj_history__') || [];
    var changed = false;
    history.forEach(function (room) {
      var before = (room.rounds || []).length;
      room.rounds = (room.rounds || []).filter(function (r) {
        return r._id !== recordId;
      });
      if (room.rounds.length !== before) changed = true;
    });
    if (changed) {
      history = history.filter(function (room) {
        return (room.rounds || []).length > 0;
      });
      wx.setStorageSync('__mj_history__', history);
    }
  },

  // ================================================================
  // 历史记录
  // ================================================================

  /** 打开历史记录 */
  onOpenHistory: function () {
    var self = this;
    self.setData({ showHistory: true, historyLoading: true, historyList: [] });
    self._loadHistory();
  },

  /** 关闭历史记录 */
  onCloseHistory: function () {
    this.setData({ showHistory: false });
  },

  /** 加载历史记录（云函数 + 本地兜底） */
  _loadHistory: function () {
    var self = this;

    // 先用本地缓存兜底展示
    var localHistory = wx.getStorageSync('__mj_history__') || [];
    if (localHistory.length > 0) {
      self.setData({ historyList: localHistory });
    }

    if (!wx.cloud) {
      self.setData({ historyLoading: false });
      return;
    }

    // 用户已清除记录 → 跳过云端拉取，避免数据回灌
    if (wx.getStorageSync('__mj_data_cleared__')) {
      self.setData({ historyLoading: false });
      return;
    }

    // 云端拉取权威数据
    wx.cloud.callFunction({
      name: 'getMjHistory',
      data: {}
    }).then(function (res) {
      if (res.result && res.result.ok && res.result.history.length > 0) {
        var cloudHistory = res.result.history.map(function (item) {
          return {
            roomCode: item.roomCode,
            startTime: item.startTime,
            settleTime: item.settleTime,
            players: item.players || [],
            gameType: item.gameType || 'mahjong'
          };
        });
        self.setData({ historyList: cloudHistory, historyLoading: false });
      } else {
        self.setData({ historyLoading: false });
        // 云端无数据，本地缓存兜底
        if (localHistory.length === 0) {
          // 无任何历史记录
        }
      }
    }).catch(function () {
      self.setData({ historyLoading: false });
    });
  }
});
