/**
 * 对局记录页 — 进行中 / 已结束
 * 数据源：进行中 = 当前活跃房间云数据；已结束 = 本地历史存储 __mj_history__
 */
var STORAGE_MJ_ROOM = '__mj_room__';
var STORAGE_MJ_HISTORY = '__mj_history__';

/** YYYY-MM-DD HH:MM:SS */
function formatDateTime(ts) {
  if (!ts) return '';
  var d = new Date(ts);
  var pad = function (n) { return n < 10 ? '0' + n : n; };
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

/** 提取 YYYY-MM */
function toMonth(ts) {
  if (!ts) return '';
  var d = new Date(ts);
  var pad = function (n) { return n < 10 ? '0' + n : n; };
  return d.getFullYear() + '-' + pad(d.getMonth() + 1);
}

/** 获取名字首字 */
function firstChar(name) {
  return (name || '?')[0];
}

/** 按名字在玩家列表中查找 */
function findPlayer(players, name) {
  if (!players || !name) return null;
  for (var i = 0; i < players.length; i++) {
    if (players[i].nickName === name) return players[i];
  }
  return null;
}

Page({
  data: {
    // 顶部 Tab
    recordTab: 'active',   // 'active' | 'settled'

    // 记录列表
    records: [],           // 当前展示的记录（已应用筛选）
    allActiveRounds: [],   // 进行中 — 所有轮次
    allSettledRounds: [],  // 已结束 — 所有已结算轮次

    // 月份筛选
    selectedMonth: '',     // '' = 全部
    availableMonths: [],
    monthPickerRange: ['全部'],

    // 状态
    loading: true,
    hasActiveRoom: false,  // 是否有活跃房间

    // 删除确认
    showDeleteConfirm: false,
    deleteTarget: null,    // { recordId, roomCode, index }
  },

  /* ==================== 生命周期 ==================== */
  onLoad: function () {
    this._loadAll();
  },

  onShow: function () {
    this._loadAll();
  },

  /* ==================== 数据加载 ==================== */
  _loadAll: function () {
    var self = this;
    self.setData({ loading: true });

    // 并行加载：活跃房间记录 + 已结算历史
    self._loadActiveRounds();
    self._loadSettledHistory();
    self._applyFilter();
    self.setData({ loading: false });
  },

  /** 加载当前活跃房间的对局记录 */
  _loadActiveRounds: function () {
    var self = this;
    var saved = wx.getStorageSync(STORAGE_MJ_ROOM);
    if (!saved || !saved.roomCode) {
      self.setData({ hasActiveRoom: false, allActiveRounds: [] });
      return;
    }

    self.setData({ hasActiveRoom: true });

    wx.cloud.callFunction({
      name: 'getRoomInfo',
      data: { roomCode: saved.roomCode }
    }).then(function (res) {
      if (!res.result.ok) {
        self.setData({ allActiveRounds: [] });
        return;
      }
      var records = (res.result.records || []);
      // 仅保留 mj_round 类型，并用 players 列表补充 avatarUrl
      var players = res.result.players || [];
      var rounds = records.filter(function (r) { return r.type === 'mj_round'; });
      rounds.forEach(function (round) {
        var deltas = round.playerDeltas || [];
        deltas.forEach(function (d) {
          var p = findPlayer(players, d.name);
          if (p) { d.avatarUrl = p.avatarUrl || ''; }
          else { d.avatarUrl = ''; }
        });
      });
      self.setData({ allActiveRounds: rounds });
      self._applyFilter();
    }).catch(function () {
      self.setData({ allActiveRounds: [] });
    });
  },

  /** 加载已结算历史 */
  _loadSettledHistory: function () {
    var history = wx.getStorageSync(STORAGE_MJ_HISTORY) || [];
    // 展平所有已结算房间的轮次，带房间信息
    var allRounds = [];
    history.forEach(function (room) {
      var roomPlayers = room.players || [];
      var rounds = room.rounds || [];
      rounds.forEach(function (r) {
        var deltas = (r.playerDeltas || []).slice(); // 浅拷贝避免污染原始数据
        // 用房间的玩家列表补充 avatarUrl
        deltas.forEach(function (d) {
          var p = findPlayer(roomPlayers, d.name);
          if (p) { d.avatarUrl = p.avatarUrl || ''; }
          else { d.avatarUrl = ''; }
        });
        allRounds.push({
          // 轮次数据
          _id: r._id,
          mode: r.mode,
          winnerName: r.winnerName,
          loserName: r.loserName,
          fanCount: r.fanCount,
          baseScore: r.baseScore,
          barScore: r.barScore,
          barPlayerName: r.barPlayerName,
          playerDeltas: deltas,
          createTime: r.createTime,
          // 房间信息
          roomCode: room.roomCode,
          settleTime: room.settleTime,
          players: roomPlayers
        });
      });
    });
    // 按时间倒序排列
    allRounds.sort(function (a, b) { return (b.createTime || 0) - (a.createTime || 0); });
    this.setData({ allSettledRounds: allRounds });
  },

  /** 提取可用月份列表 */
  _getAvailableMonths: function (rounds) {
    var months = {};
    rounds.forEach(function (r) {
      var m = toMonth(r.createTime);
      if (m) months[m] = true;
    });
    return Object.keys(months).sort().reverse();
  },

  /** 应用 Tab + 月份筛选 */
  _applyFilter: function () {
    var self = this;
    var isActive = self.data.recordTab === 'active';
    var source = isActive ? self.data.allActiveRounds : self.data.allSettledRounds;
    var month = self.data.selectedMonth;

    var filtered = source;
    if (month) {
      filtered = source.filter(function (r) {
        return toMonth(r.createTime) === month;
      });
    }

    var months = self._getAvailableMonths(source);

    self.setData({
      records: filtered,
      availableMonths: months,
      monthPickerRange: ['全部'].concat(months)
    });
  },

  /* ==================== Tab 切换 ==================== */
  onRecordTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ recordTab: tab, selectedMonth: '' });
    this._applyFilter();
  },

  /* ==================== 月份筛选（picker 下拉） ==================== */
  onMonthPickerChange: function (e) {
    var index = e.detail.value;          // picker 返回选中项索引
    var range = this.data.monthPickerRange;
    var month = index === 0 ? '' : range[index];  // 索引 0 = 全部
    this.setData({ selectedMonth: month });
    this._applyFilter();
  },

  /* ==================== 删除记录 ==================== */
  onDeleteRound: function (e) {
    var recordId = e.currentTarget.dataset.id;
    var roomCode = e.currentTarget.dataset.room;
    var index = e.currentTarget.dataset.index;
    this.setData({
      showDeleteConfirm: true,
      deleteTarget: { recordId: recordId, roomCode: roomCode, index: index }
    });
  },

  confirmDelete: function () {
    var self = this;
    var target = self.data.deleteTarget;
    if (!target) return;

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
      var isActive = self.data.recordTab === 'active';
      if (isActive) {
        var activeRounds = self.data.allActiveRounds.filter(function (r) {
          return r._id !== target.recordId;
        });
        self.setData({ allActiveRounds: activeRounds });
      } else {
        var settledRounds = self.data.allSettledRounds.filter(function (r) {
          return r._id !== target.recordId;
        });
        self.setData({ allSettledRounds: settledRounds });
        // 同步更新本地历史存储
        self._syncHistoryDelete(target.recordId);
      }
      self.setData({ showDeleteConfirm: false, deleteTarget: null });
      self._applyFilter();
      wx.showToast({ title: '已删除', icon: 'success' });
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: '删除失败: ' + (err.errMsg || '网络错误'), icon: 'none' });
    });
  },

  cancelDelete: function () {
    this.setData({ showDeleteConfirm: false, deleteTarget: null });
  },

  /** 同步删除到本地历史存储 */
  _syncHistoryDelete: function (recordId) {
    var history = wx.getStorageSync(STORAGE_MJ_HISTORY) || [];
    var changed = false;
    history.forEach(function (room) {
      var before = (room.rounds || []).length;
      room.rounds = (room.rounds || []).filter(function (r) {
        return r._id !== recordId;
      });
      if (room.rounds.length !== before) changed = true;
    });
    if (changed) {
      // 移除没有轮次的空房间
      history = history.filter(function (room) {
        return (room.rounds || []).length > 0;
      });
      wx.setStorageSync(STORAGE_MJ_HISTORY, history);
    }
  },

  /* ==================== 底部导航 ==================== */
  onNavHome: function () {
    wx.redirectTo({ url: '/pages/mahjong_scoring/mahjong_scoring' });
  },

  onNavMine: function () {
    wx.redirectTo({ url: '/pages/mahjong_scoring/mahjong_scoring' });
  },

  /* ==================== 格式化辅助 ==================== */
  /** 获取轮次中最高分的玩家（赢家） */
  _getTopPlayer: function (deltas) {
    if (!deltas || deltas.length === 0) return null;
    var top = deltas[0];
    for (var i = 1; i < deltas.length; i++) {
      if (deltas[i].delta > top.delta) top = deltas[i];
    }
    return top;
  },

  /** 获取轮次中最低分的玩家（输家） */
  _getBottomPlayer: function (deltas) {
    if (!deltas || deltas.length === 0) return null;
    var bottom = deltas[0];
    for (var i = 1; i < deltas.length; i++) {
      if (deltas[i].delta < bottom.delta) bottom = deltas[i];
    }
    return bottom;
  },

  /** 格式化轮次数据供 WXML 使用 */
  _formatRecord: function (r) {
    var deltas = r.playerDeltas || [];
    var top = this._getTopPlayer(deltas);
    var bottom = this._getBottomPlayer(deltas);
    return {
      _id: r._id,
      roomCode: r.roomCode,
      mode: r.mode,
      winnerName: r.winnerName || (top ? top.name : ''),
      loserName: r.loserName || (bottom && bottom !== top ? bottom.name : ''),
      fanCount: r.fanCount,
      baseScore: r.baseScore,
      barScore: r.barScore,
      barPlayerName: r.barPlayerName,
      playerDeltas: deltas,
      topPlayer: top,
      bottomPlayer: bottom,
      timeStr: formatDateTime(r.createTime),
      createTime: r.createTime
    };
  }
});
