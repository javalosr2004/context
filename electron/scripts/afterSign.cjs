const { execSync } = require('child_process')
const path = require('path')

exports.default = async function afterSign(context) {
  if (context.electronPlatformName !== 'darwin') return

  const appPath = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`
  )

  console.log(`  • re-signing app bundle with consistent ad-hoc identity`)
  execSync(`codesign --force --deep --sign - "${appPath}"`, { stdio: 'inherit' })
}
