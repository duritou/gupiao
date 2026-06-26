const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

exports.main = async (event, context) => {
  const { OPENID, UNIONID } = cloud.getWXContext()
  return { openId: OPENID, unionId: UNIONID || '' }
}
