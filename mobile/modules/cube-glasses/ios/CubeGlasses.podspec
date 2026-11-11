require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |s|
  s.name           = 'CubeGlasses'
  s.version        = package['version']
  s.summary        = package['description']
  s.description    = package['description']
  s.license        = package['license']
  s.author         = package['author']
  s.homepage       = package['homepage']
  s.platforms      = { :ios => '17.2' }   # the Meta DAT SDK's minimum
  s.swift_version  = '5.9'
  s.source         = { git: 'https://github.com/facebook/meta-wearables-dat-ios' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  # Meta Wearables Device Access Toolkit 1.0.1 (dynamic xcframeworks). Downloaded by
  # scripts/fetch-ios-sdk.js on `npm install`; CocoaPods embeds them in the app.
  frameworks_dir = File.join(__dir__, 'Frameworks')
  unless File.exist?(File.join(frameworks_dir, 'MWDATCore.xcframework'))
    raise "[CubeGlasses] Meta DAT iOS SDK missing. Run: node modules/cube-glasses/scripts/fetch-ios-sdk.js"
  end
  s.vendored_frameworks = 'Frameworks/MWDATCore.xcframework',
                          'Frameworks/MWDATCamera.xcframework',
                          'Frameworks/MWDATMockDevice.xcframework'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = '*.swift'
end
