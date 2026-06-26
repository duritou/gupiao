// pages/order/index.js
import network from '../../../utils/hotel-network';
/*
 * @Author: yurui 
 * @Date: 2021-05-28
 */
import Dialog from '../../../vant-weapp/dist/dialog/dialog';
import {
  domain
} from '../../../utils/hotel-config';
import {
  moment
} from '../../../utils/hotel-util';

Page({

  /**
   * 页面的初始数据
   */
  data: {
    active: 0,
    domain,
    all: [],
    pay: [],
    check: [],
    finish: [],
    _initialized: false, // 首次加载标记，避免 onShow 重复刷新
  },

  goDetails(e) {
    wx.navigateTo({
      url: `/pages/hotel/orderDetails/index?id=${e.currentTarget.id}`
    });
  },

  getData(query, type) {
    const that = this;
    network.request({
      url: `order/list`,
      data: query,
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100010) {
          if (type == 'finish') {
            const datas = [...that.data.finish, ...res.data.data];
            that.setData({
              [type]: datas,
            });
          } else {
            that.setData({
              [type]: res.data.data,
            });
          }
        }
      },
      fail(res) {
        wx.showToast({
          title: '数据请求失败',
          icon: 'error',
          duration: 2000
        });
      },
    });
  },

  onCancel(e) {
    const now = moment(moment(new Date()).format('YYYY-MM-DD H:mm:ss'));
    const startTime = moment(moment(`${e.target.dataset.time} 18:00:00`).format('YYYY-MM-DD H:mm:ss'));
    const minute = startTime.diff(now, 'minute');
    const hours = Math.floor(minute / 60);
    if (hours < 24 && e.target.dataset.pay == 1) {
      wx.showToast({
        title: '入住时间小于24小时的订单，不能取消！',
        icon: 'none',
        duration: 2000
      });
      return;
    }
    const that = this;
    Dialog.confirm({
        title: '取消订单',
        message: '请确认是否要继续执行该操作？',
      })
      .then(() => {
        network.request({
          url: `order/cancel`,
          method: 'POST',
          data: {
            id: e.target.dataset.id,
            room: e.target.dataset.room,
          },
          header: {
            'content-type': 'application/json'
          },
          success(res) {
            if (res.data.code == 100030) {
              wx.showToast({
                title: '订单取消成功！',
                icon: 'success',
                duration: 2000
              });
              setTimeout(() => {
                wx.navigateTo({
                  url: `/pages/hotel/orderDetails/index?id=${e.target.dataset.id}`
                });
              }, 1500)
            } else {
              wx.showToast({
                title: '订单取消失败，请电话联系我们！',
                icon: 'none',
                duration: 2000
              });
            }
          },
          fail(res) {
            wx.showToast({
              title: '数据请求失败',
              icon: 'error',
              duration: 2000
            });
          },
        });
      })
      .catch(() => {
        // on cancel
      });
  },

  goHome() {
    wx.navigateTo({
      url: `/pages/hotel/index/index`
    });
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad: function (options) {
    this.setData({
      all: [],
      pay: [],
      check: [],
      finish: [],
    });
    this.getData({}, 'all');
    this.getData({
      pay_status: 0,
      status: 2,
    }, 'pay');
    this.getData({
      pay_status: 1,
      status: 2,
    }, 'check');
    this.getData({
      status: 3,
    }, 'finish');
    this.getData({
      status: 4,
    }, 'finish');
    this.setData({
      active: Number(options.active),
      _initialized: true,
    });
  },

  /**
   * 生命周期函数--监听页面初次渲染完成
   */
  onReady: function () {

  },

  /**
   * 生命周期函数--监听页面显示
   */
  onShow: function () {
    // 从详情页返回时刷新列表（首次加载由 onLoad 处理）
    if (this.data._initialized) {
      this.setData({
        all: [],
        pay: [],
        check: [],
        finish: [],
      });
      this.getData({}, 'all');
      this.getData({ pay_status: 0, status: 2 }, 'pay');
      this.getData({ pay_status: 1, status: 2 }, 'check');
      this.getData({ status: 3 }, 'finish');
      this.getData({ status: 4 }, 'finish');
    }
  },

  /**
   * 生命周期函数--监听页面隐藏
   */
  onHide: function () {

  },

  /**
   * 生命周期函数--监听页面卸载
   */
  onUnload: function () {

  },

  /**
   * 页面相关事件处理函数--监听用户下拉动作
   */
  onPullDownRefresh: function () {
    // 重置列表并重新加载所有分类数据
    this.setData({
      all: [],
      pay: [],
      check: [],
      finish: [],
    });
    this.getData({}, 'all');
    this.getData({ pay_status: 0, status: 2 }, 'pay');
    this.getData({ pay_status: 1, status: 2 }, 'check');
    this.getData({ status: 3 }, 'finish');
    this.getData({ status: 4 }, 'finish');
    wx.stopPullDownRefresh();
  },

  /**
   * 页面上拉触底事件的处理函数
   */
  onReachBottom: function () {

  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage: function () {

  }
})