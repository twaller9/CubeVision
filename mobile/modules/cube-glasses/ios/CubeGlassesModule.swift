import ExpoModulesCore
import UIKit

/// The phone side of CubeVision on iOS: glasses camera -> web app, web app -> glasses
/// speakers, optional glasses mic -> web app. Same JS API and events as Android.
public final class CubeGlassesModule: Module {
  private let link = ServerLink()
  private let audio = AudioBridge()
  private let glasses = GlassesController()

  public func definition() -> ModuleDefinition {
    Name("CubeGlasses")

    Events("onRegistration", "onDevices", "onStatus", "onStream", "onPreview", "onServer", "onServerEvent")

    OnCreate {
      let link = self.link
      self.link.onEvent = { [weak self] text in self?.handleServerEvent(text) }
      self.link.onConnection = { [weak self] connected, status in
        self?.sendEvent("onServer", ["connected": connected, "status": status])
      }
      self.audio.sendMic = { [weak link] pcm in link?.sendAudio(pcm) }
      self.glasses.emit = { [weak self] name, body in self?.sendEvent(name, body) }
      self.glasses.onJPEG = { [weak link] jpeg in link?.sendFrame(jpeg) }
    }

    AsyncFunction("initialize") { () async -> String in
      await self.glasses.initialize()
    }

    AsyncFunction("startRegistration") { () async in
      await self.glasses.startRegistration()
    }

    AsyncFunction("startUnregistration") { () async in
      await self.glasses.startUnregistration()
    }

    AsyncFunction("requestCameraPermission") { () async -> String in
      await self.glasses.requestCameraPermission()
    }

    AsyncFunction("setMockGlasses") { (enabled: Bool) async -> String in
      await self.glasses.setMockGlasses(enabled)
    }

    AsyncFunction("startStreaming") { (fps: Int) async -> String in
      await self.glasses.startStreaming(fps: fps)
    }

    AsyncFunction("stopStreaming") { () async in
      await self.glasses.stopStreaming()
    }

    AsyncFunction("connect") { (url: String) in
      self.link.connect(url)
    }

    AsyncFunction("disconnect") {
      self.link.disconnect()
    }

    AsyncFunction("send") { (json: String) -> Bool in
      self.link.sendText(json)
      return true
    }

    AsyncFunction("setSpeakFallback") { (on: Bool) in
      self.audio.speakTextFallback = on
    }.runOnQueue(.main)

    AsyncFunction("setMicForwarding") { (on: Bool) async -> String in
      await self.audio.setMicForwarding(on)
    }

    AsyncFunction("setKeepScreenOn") { (on: Bool) in
      UIApplication.shared.isIdleTimerDisabled = on
    }.runOnQueue(.main)

    Function("getPref") { (key: String) -> String? in
      UserDefaults.standard.string(forKey: "cubeglasses.\(key)")
    }

    Function("setPref") { (key: String, value: String) in
      UserDefaults.standard.set(value, forKey: "cubeglasses.\(key)")
    }

    OnDestroy {
      let glasses = self.glasses
      let audio = self.audio
      Task { @MainActor in
        glasses.stopStreaming()
        audio.shutdown()
      }
      self.link.shutdown()
    }
  }

  /// Runs on the main queue (ServerLink delivers there).
  private func handleServerEvent(_ text: String) {
    guard let data = text.data(using: .utf8),
          var event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    else { return }
    audio.onServerEvent(event)
    // Audio stays on the native side; JS only needs the text.
    event.removeValue(forKey: "audio_b64")
    if let slim = try? JSONSerialization.data(withJSONObject: event),
       let json = String(data: slim, encoding: .utf8) {
      sendEvent("onServerEvent", ["json": json])
    }
  }
}
