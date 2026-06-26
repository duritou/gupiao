// pages/pay/index.js
import network from '../../../utils/hotel-network';
/*
 * @Author: yurui 
 * @Date: 2021-05-28
 */
import Dialog from '../../../vant-weapp/dist/dialog/dialog';
import {
  moment
} from '../../../utils/hotel-util';

Page({

  /**
   * 页面的初始数据
   */
  data: {
    datas: {},
    roomNum: 0,
    ids: '',
    countdownTime: 0, // 剩余支付时间（毫秒）
  },

  getData(ids) {
    const that = this;
    network.request({
      url: `order/more`,
      method: 'POST',
      data: {
        ids,
      },
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100010) {
          const days = moment(res.data.data.end_time).diff(moment(res.data.data.start_time), 'days');
          // 计算订单剩余支付时间（创建时间 + 30 分钟 - 当前时间）
          const createdAt = res.data.data.createdAt || res.data.data.created_at;
          let countdownTime = 0;
          if (createdAt) {
            const expireTime = moment(createdAt).valueOf() + 30 * 60 * 1000;
            countdownTime = Math.max(0, expireTime - Date.now());
          }
          that.setData({
            datas: {
              ...res.data.data,
              days
            },
            countdownTime,
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
  },

  onPay() {
    const that = this;
    if (this.data.ids) {
      network.request({
        url: `pay/unifiedorder`,
        method: 'POST',
        data: {
          ids: that.data.ids,
        },
        header: {
          'content-type': 'application/json'
        },
        success(res) {
          if (res.data.code == 100020) {
            wx.requestPayment({
              ...res.data.data,
              success(res) {
                wx.redirectTo({
                  url: '/pages/hotel/order/index'
                });
              },
              fail(res) {
                wx.showToast({
                  title: '支付失败',
                  icon: 'error',
                  duration: 2000
                });
              }
            });
          } else {
            wx.showToast({
              title: '系统错误',
              icon: 'error',
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
    }
  },

  // 支付倒计时归零时自动返回订单列表
  onCountDownFinish() {
    wx.showToast({
      title: '订单已超时',
      icon: 'none',
      duration: 2000
    });
    setTimeout(() => {
      wx.redirectTo({
        url: '/pages/hotel/order/index'
      });
    }, 2000);
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad: function (options) {
    this.getData(options.ids);
    this.setData({
      roomNum: options.succes,
      ids: options.ids,
    });
    if (options.roomNum != options.succes) {
      Dialog.confirm({
          title: '部分预定成功',
          message: `非常抱歉，您想预定 ${options.roomNum} 间房，实际预定成功 ${options.succes} 间房，请确认是否继续完成支付？`,
        })
        .then(() => {
          // on confirm
        })
        .catch(() => {
          wx.redirectTo({
            url: '/pages/hotel/order/index?active=1'
          });
        });
    }
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