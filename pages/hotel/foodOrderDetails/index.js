// pages/orderDetails/index.js
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
          const foodsArr = changeCarData(arr);
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

  goHome() {
    wx.navigateTo({
      url: `/pages/hotel/food/index`
    });
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad: function (options) {
    this.getData(options.id);
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