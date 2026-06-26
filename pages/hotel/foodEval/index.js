// pages/foodEval/index.js
import network from '../../../utils/hotel-network';
/*
 * @Author: yurui 
 * @Date: 2021-05-28
 */
import {
  domain
} from '../../../utils/hotel-config';
import {
  changeCarData
} from '../../../utils/hotel-util';

Page({

  /**
   * 页面的初始数据
   */
  data: {
    datas: {},
    domain,
    foods: [],
    id: '',
  },

  getData(id) {
    const that = this;
    network.request({
      url: `food/order/details/${id}`,
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100010) {
          const arr = [];
          const idArr = res.data.data.food_ids.split(',');
          const foods = res.data.data.foods;
          for (let i = 0; i < idArr.length; i++) {
            for (let j = 0; j < foods.length; j++) {
              if (idArr[i] == foods[j].id) {
                arr.push({
                  ...foods[j],
                  num: 1,
                });
              }
            }
          }
          let name = '匿名用户';
          const userInfo = wx.getStorageSync('userInfo');
          if (userInfo.nickName) {
            name = userInfo.nickName;
          }
          const foodsArr = changeCarData(arr).map(item => ({
            ...item,
            good: '1',
            name,
            content: '',
          }));
          that.setData({
            datas: res.data.data,
            foods: foodsArr,
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

  onChangeRadio(e) {
    const foods = [...this.data.foods];
    foods[e.currentTarget.dataset.index].good = e.detail;
    this.setData({
      foods,
    });
  },

  onChangeInput(e) {
    const foods = [...this.data.foods];
    foods[e.currentTarget.dataset.index].content = e.detail;
    this.setData({
      foods,
    });
  },

  goHome() {
    wx.navigateTo({
      url: `/pages/hotel/food/index`
    });
  },

  goSubmit() {
    const that = this;
    network.request({
      url: `food/eval/create`,
      method: 'POST',
      data: {
        orderId: that.data.id,
        evals: that.data.foods,
      },
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100020) {
          wx.showToast({
            title: '提交评论成功',
            icon: 'success',
            duration: 2000
          });
          setTimeout(() => {
            wx.redirectTo({
              url: `/pages/hotel/foodMyEval/index`
            });
          }, 1500);
        } else {
          wx.showToast({
            title: '提交失败！',
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
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad: function (options) {
    this.getData(options.id);
    this.setData({
      id: options.id,
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