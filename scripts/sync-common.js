// scripts/sync-common.js
// 把领域核心层 cloudfunctions/common/ 同步拷贝到每个引用它的云函数目录下（common/ 子目录）。
//
// 为什么需要：微信云开发「上传并部署：云端安装依赖」模型下，每个云函数是独立计算单元，
// 只上传自身文件夹，拿不到兄弟目录 cloudfunctions/common/，file:../common 会在云端 npm install 时失败。
// 故改用本地物理拷贝：云函数 require('./common') 读取自身目录下的 common/ 子目录，
// 副本由本脚本生成、源头单一（cloudfunctions/common/）、gitignore 不入库。
//
// 用法：node scripts/sync-common.js  （每次改完 common、或部署云函数前执行一次）

const fs = require('fs')
const path = require('path')

const repoRoot = path.resolve(__dirname, '..')
const srcDir = path.join(repoRoot, 'cloudfunctions', 'common')

// 引用 common 的云函数清单（新增消费者时在此追加）
const CONSUMERS = ['getRoomInfo', 'joinRoom', 'addScoreRecord', 'takeFromPool']

// 待拷贝的源文件：读取 common/ 下所有文件，排除 __tests__ 等非运行时目录
const files = fs.readdirSync(srcDir).filter(name => {
  if (name === '__tests__') return false
  return fs.statSync(path.join(srcDir, name)).isFile()
})

console.log('[sync-common] 源目录:', path.relative(repoRoot, srcDir))
console.log('[sync-common] 待拷贝文件:', files.join(', '))

for (const func of CONSUMERS) {
  const destDir = path.join(repoRoot, 'cloudfunctions', func, 'common')
  // 先清空旧副本，避免源文件删除后残留
  fs.rmSync(destDir, { recursive: true, force: true })
  fs.mkdirSync(destDir, { recursive: true })
  for (const f of files) {
    fs.copyFileSync(path.join(srcDir, f), path.join(destDir, f))
  }
  console.log('[sync-common] 已同步 →', path.relative(repoRoot, destDir), `(${files.length} 文件)`)
}

console.log('[sync-common] 完成。请用「上传并部署：云端安装依赖」逐个部署云函数。')
