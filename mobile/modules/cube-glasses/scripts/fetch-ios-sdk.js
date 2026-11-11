/* global __dirname */
// Downloads Meta's Wearables Device Access Toolkit xcframeworks for the iOS build.
// Runs on `npm install` (postinstall). Only needed on macOS (local iOS builds and EAS iOS
// workers); skipped elsewhere unless CUBEGLASSES_FETCH_IOS_SDK=1.
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const VERSION = '1.0.1';
const FRAMEWORKS = ['MWDATCore', 'MWDATCamera', 'MWDATMockDevice'];
const dest = path.join(__dirname, '..', 'ios', 'Frameworks');
const stamp = path.join(dest, `.version-${VERSION}`);

if (process.platform !== 'darwin' && process.env.CUBEGLASSES_FETCH_IOS_SDK !== '1') {
  console.log('[cube-glasses] not macOS, skipping iOS SDK download');
  process.exit(0);
}
if (fs.existsSync(stamp) && FRAMEWORKS.every((f) => fs.existsSync(path.join(dest, `${f}.xcframework`)))) {
  console.log(`[cube-glasses] Meta DAT iOS SDK ${VERSION} already present`);
  process.exit(0);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mwdat-'));
const tgz = path.join(tmp, 'sdk.tgz');
const url = `https://github.com/facebook/meta-wearables-dat-ios/archive/refs/tags/${VERSION}.tar.gz`;
console.log(`[cube-glasses] downloading Meta DAT iOS SDK ${VERSION}…`);
execFileSync('curl', ['-fsSL', '--retry', '3', '-o', tgz, url], { stdio: 'inherit' });
const root = `meta-wearables-dat-ios-${VERSION}`;
execFileSync('tar', ['-xzf', tgz, '-C', tmp, ...FRAMEWORKS.map((f) => `${root}/${f}.xcframework`)], {
  stdio: 'inherit',
});
fs.rmSync(dest, { recursive: true, force: true });
fs.mkdirSync(dest, { recursive: true });
for (const f of FRAMEWORKS) {
  fs.renameSync(path.join(tmp, root, `${f}.xcframework`), path.join(dest, `${f}.xcframework`));
}
fs.writeFileSync(stamp, url + '\n');
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`[cube-glasses] installed ${FRAMEWORKS.join(', ')} into ${dest}`);
