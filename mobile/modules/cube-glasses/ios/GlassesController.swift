import Foundation
import MWDATCamera
import MWDATCore
import MWDATMockDevice
import UIKit

/// Wraps the Meta Wearables Device Access Toolkit: registration, camera permission,
/// device session and camera stream. Frames are JPEG-encoded and handed to `onJPEG`
/// (throttled). No cube logic lives on the phone.
final class GlassesController {
  /// (event name, body) — forwarded to JS.
  var emit: (String, [String: Any?]) -> Void = { _, _ in }
  /// Called off the main thread with each JPEG to forward to the server.
  var onJPEG: (Data) -> Void = { _ in }

  /// URLs from the Meta AI app that arrived before the SDK was configured.
  static var pendingURLs: [URL] = []
  static weak var current: GlassesController?

  private var configured = false
  private var session: DeviceSession?
  private var camera: Camera?
  private var stream: MWDATCamera.Stream?
  private var streamWasActive = false
  private var tokens: [any AnyListenerToken] = []
  private var sessionTasks: [Task<Void, Never>] = []
  private var mockGlasses: (any MockGlasses)?
  private let sendThrottle = FrameThrottle(interval: 0.2)
  private let previewThrottle = FrameThrottle(interval: 0.7)

  // MARK: Setup

  @MainActor
  func initialize() -> String {
    if configured { return "ok" }
    do {
      try Wearables.configure()
    } catch WearablesError.alreadyConfigured {
      // Configured earlier in this process (a JS reload created a new module) — carry on.
    } catch {
      return "error: \(error)"
    }
    configured = true
    GlassesController.current = self
    let wearables = Wearables.shared
    Task { @MainActor [weak self] in
      for await state in wearables.registrationStateStream() {
        self?.emit("onRegistration", ["state": Self.name(of: state)])
      }
    }
    Task { @MainActor [weak self] in
      for await devices in wearables.devicesStream() {
        self?.emit("onDevices", ["count": devices.count])
      }
    }
    let pending = GlassesController.pendingURLs
    GlassesController.pendingURLs = []
    for url in pending {
      Task { await self.handle(url: url) }
    }
    return "ok"
  }

  /// Callback from the Meta AI app (registration / permission result).
  @discardableResult
  func handle(url: URL) async -> Bool {
    do {
      return try await Wearables.shared.handleUrl(url)
    } catch {
      await status("Meta AI callback error: \(error)")
      return false
    }
  }

  func startRegistration() async {
    do {
      try await Wearables.shared.startRegistration()
    } catch {
      await status("Registration: \(error)")
    }
  }

  func startUnregistration() async {
    do {
      try await Wearables.shared.startUnregistration()
    } catch {
      await status("Unregistration: \(error)")
    }
  }

  func requestCameraPermission() async -> String {
    do {
      var permission = try await Wearables.shared.checkPermissionStatus(.camera)
      if permission != .granted {
        permission = try await Wearables.shared.requestPermission(.camera)
      }
      return permission == .granted ? "granted" : "denied"
    } catch {
      await status("Camera permission: \(error)")
      return "denied"
    }
  }

  /// Mock glasses: the phone's back camera pretends to be the glasses camera.
  @MainActor
  func setMockGlasses(_ enabled: Bool) async -> String {
    let kit = MockDeviceKit.shared
    if enabled {
      if !kit.isEnabled {
        kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true))
      }
      if mockGlasses == nil {
        do {
          let glasses = try kit.pairGlasses(model: .rayBanMeta)
          glasses.powerOn()
          glasses.unfold()
          glasses.don()
          glasses.services.camera.setCameraFeed(cameraFacing: .back)
          mockGlasses = glasses
        } catch {
          return "error: could not create mock glasses (\(error))"
        }
      }
      return "ok"
    }
    stopStreaming()
    if let glasses = mockGlasses {
      await kit.unpairDevice(glasses)
    }
    mockGlasses = nil
    if kit.isEnabled {
      await kit.disable()
    }
    return "ok"
  }

  // MARK: Streaming

  @MainActor
  func startStreaming(fps: Int) -> String {
    // A tap on "Start" always begins from a clean slate, even if an old session is stuck.
    if session != nil { stopStreaming() }
    sendThrottle.interval = 1.0 / Double(min(max(fps, 1), 15))

    let wearables = Wearables.shared
    let newSession: DeviceSession
    do {
      newSession = try wearables.createSession(deviceSelector: AutoDeviceSelector(wearables: wearables))
    } catch {
      status("Couldn't connect to glasses: \(error)")
      return "error: \(error)"
    }
    session = newSession
    emit("onStream", ["state": "STARTING"]) // lets the UI show "Stop" right away

    // Create the streams before start() so no transitions are missed.
    let states = newSession.stateStream()
    let errors = newSession.errorStream()
    sessionTasks.append(Task { @MainActor [weak self] in
      for await error in errors {
        self?.status("Glasses: \(error)")
      }
    })
    sessionTasks.append(Task { @MainActor [weak self] in
      for await state in states {
        guard let self, self.session === newSession else { return }
        self.status("Glasses session: \(state)")
        switch state {
        case .started:
          if self.camera == nil { self.startCamera(on: newSession) }
        case .stopped:
          self.cleanup()
          return
        default:
          break
        }
      }
    })

    do {
      try newSession.start()
    } catch {
      status("Couldn't start glasses session: \(error)")
      stopStreaming()
      return "error: \(error)"
    }
    return "ok"
  }

  @MainActor
  private func startCamera(on activeSession: DeviceSession) {
    // Medium (504x896) at 15 fps keeps Bluetooth compression low while still giving the
    // vision model enough pixels per sticker.
    let config = StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 15)
    let cam: Camera
    do {
      guard let added = try activeSession.addCamera(config: config) else {
        status("Glasses camera unavailable")
        stopStreaming()
        return
      }
      cam = added
    } catch {
      status("Couldn't open glasses camera: \(error)")
      stopStreaming()
      return
    }
    camera = cam
    let stream = cam.stream
    self.stream = stream
    streamWasActive = false

    tokens.append(stream.statePublisher.listen { [weak self] state in
      Task { @MainActor in self?.onStreamState(state, camera: cam) }
    })
    tokens.append(stream.errorPublisher.listen { [weak self] error in
      Task { @MainActor in self?.status("Camera: \(error)") }
    })

    let sendThrottle = self.sendThrottle
    let previewThrottle = self.previewThrottle
    let forward = self.onJPEG
    let emit = self.emit
    tokens.append(stream.videoFramePublisher.listen { frame in
      let wantSend = sendThrottle.tick()
      let wantPreview = previewThrottle.tick()
      guard wantSend || wantPreview,
            let image = frame.makeUIImage(),
            let jpeg = image.jpegData(compressionQuality: 0.75)
      else { return }
      if wantSend { forward(jpeg) }
      if wantPreview {
        let body: [String: Any?] = [
          "jpeg": jpeg.base64EncodedString(),
          "width": Int(image.size.width * image.scale),
          "height": Int(image.size.height * image.scale),
        ]
        DispatchQueue.main.async { emit("onPreview", body) }
      }
    })

    stream.start()
  }

  @MainActor
  private func onStreamState(_ state: StreamState, camera cam: Camera) {
    emit("onStream", ["state": Self.name(of: state)])
    switch state {
    case .waitingForDevice, .starting, .streaming, .paused:
      streamWasActive = true
    case .stopped:
      // The glasses ended the stream on their own (folded, too hot, battery, ...).
      if streamWasActive && camera === cam {
        streamWasActive = false
        status("Glasses camera stopped")
        stopStreaming()
      }
    case .stopping:
      break
    }
  }

  @MainActor
  func stopStreaming() {
    stream?.stop()
    camera?.stop()
    session?.stop()
    cleanup()
  }

  @MainActor
  private func cleanup() {
    let oldTokens = tokens
    tokens = []
    Task {
      for token in oldTokens { await token.cancel() }
    }
    let oldTasks = sessionTasks
    sessionTasks = []
    stream = nil
    camera = nil
    session = nil
    streamWasActive = false
    emit("onStream", ["state": "STOPPED"])
    oldTasks.forEach { $0.cancel() }
  }

  @MainActor
  private func status(_ text: String) {
    NSLog("[CubeGlasses] %@", text)
    emit("onStatus", ["status": text])
  }

  // Same strings as the Android side so the JS UI doesn't care which platform it's on.
  static func name(of state: RegistrationState) -> String {
    switch state {
    case .unavailable: return "UNAVAILABLE"
    case .available: return "AVAILABLE"
    case .registering: return "REGISTERING"
    case .registered: return "REGISTERED"
    }
  }

  static func name(of state: StreamState) -> String {
    switch state {
    case .stopping: return "STOPPING"
    case .stopped: return "STOPPED"
    case .waitingForDevice: return "WAITING_FOR_DEVICE"
    case .starting: return "STARTING"
    case .streaming: return "STREAMING"
    case .paused: return "PAUSED"
    }
  }
}

/// Thread-safe "at most once every N seconds" gate, used from the SDK's frame callback.
final class FrameThrottle: @unchecked Sendable {
  private let lock = NSLock()
  private var last = Date.distantPast
  private var _interval: TimeInterval

  init(interval: TimeInterval) { _interval = interval }

  var interval: TimeInterval {
    get { lock.lock(); defer { lock.unlock() }; return _interval }
    set { lock.lock(); _interval = newValue; lock.unlock() }
  }

  func tick() -> Bool {
    lock.lock()
    defer { lock.unlock() }
    let now = Date()
    guard now.timeIntervalSince(last) >= _interval else { return false }
    last = now
    return true
  }
}
