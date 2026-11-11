import AVFoundation
import Foundation

/// Plays what the web app says on the glasses (a Bluetooth audio device), and can forward
/// the glasses mic up to the web app for the speech-to-speech side. No speech logic here.
/// Call everything on the main queue.
final class AudioBridge: NSObject, AVAudioPlayerDelegate {
  var sendMic: (Data) -> Void = { _ in }
  /// Speak the "say" text on the phone when the server didn't send audio.
  var speakTextFallback = true

  /// Event types whose speech replaces anything still queued.
  private static let interrupting: Set<String> = ["welcome", "reset", "solution", "progress", "off_track", "lost"]

  private let synth = AVSpeechSynthesizer()
  private var player: AVAudioPlayer?
  private var audioQueue: [Data] = []
  private let engine = AVAudioEngine()
  private(set) var micOn = false
  /// nil = not set yet; true = mic mode (HFP); false = playback only (A2DP).
  private var sessionMicMode: Bool?

  /// Playback-only uses A2DP (good quality on the glasses). HFP (call audio) is only used
  /// while the glasses mic is being forwarded, like Android's SCO mode.
  private func configureSession(mic: Bool = false) {
    guard sessionMicMode != mic else { return }
    sessionMicMode = mic
    let session = AVAudioSession.sharedInstance()
    if mic {
      try? session.setCategory(.playAndRecord, mode: .voiceChat,
                               options: [.allowBluetooth, .allowBluetoothA2DP, .defaultToSpeaker])
    } else {
      try? session.setCategory(.playback, mode: .spokenAudio, options: [])
    }
    try? session.setActive(true)
  }

  // MARK: Playback

  /// Lines are queued so one burst of events ("I found a solution…" then the first step)
  /// is spoken in full, while events that start something new drop whatever is stale.
  func onServerEvent(_ event: [String: Any]) {
    configureSession()
    let type = event["type"] as? String ?? ""
    let interrupt = Self.interrupting.contains(type)
    if let b64 = event["audio_b64"] as? String, !b64.isEmpty, let data = Data(base64Encoded: b64) {
      if interrupt {
        synth.stopSpeaking(at: .immediate)
        player?.stop()
        player = nil
        audioQueue.removeAll()
      }
      audioQueue.append(data)
      if player == nil { playNext() }
    } else if speakTextFallback, let say = event["say"] as? String, !say.isEmpty {
      if interrupt { synth.stopSpeaking(at: .immediate) }
      let utterance = AVSpeechUtterance(string: say)
      utterance.rate = 0.52
      synth.speak(utterance) // AVSpeechSynthesizer queues utterances itself
    }
  }

  private func playNext() {
    while !audioQueue.isEmpty {
      let data = audioQueue.removeFirst()
      do {
        let p = try AVAudioPlayer(data: data)
        p.delegate = self
        player = p
        p.play()
        return
      } catch {
        NSLog("[CubeGlasses] audio playback failed: %@", "\(error)")
      }
    }
    player = nil
  }

  func audioPlayerDidFinishPlaying(_ p: AVAudioPlayer, successfully flag: Bool) {
    DispatchQueue.main.async {
      guard p === self.player else { return }
      self.player = nil
      self.playNext()
    }
  }

  func audioPlayerDecodeErrorDidOccur(_ p: AVAudioPlayer, error: Error?) {
    audioPlayerDidFinishPlaying(p, successfully: false)
  }

  // MARK: Mic -> server (16 kHz mono PCM16)

  @MainActor
  func setMicForwarding(_ on: Bool) async -> String {
    if !on {
      stopMic()
      return "off"
    }
    if micOn { return "on" }
    let granted = await AVAudioApplication.requestRecordPermission()
    guard granted else { return "no-permission" }
    configureSession(mic: true)

    let input = engine.inputNode
    let inFormat = input.outputFormat(forBus: 0)
    guard inFormat.sampleRate > 0,
          let outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true),
          let converter = AVAudioConverter(from: inFormat, to: outFormat)
    else { return "error: microphone unavailable" }

    let send = sendMic
    input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { buffer, _ in
      let ratio = outFormat.sampleRate / inFormat.sampleRate
      let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16
      guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return }
      var fed = false
      _ = converter.convert(to: out, error: nil) { _, status in
        if fed {
          status.pointee = .noDataNow
          return nil
        }
        fed = true
        status.pointee = .haveData
        return buffer
      }
      guard let channel = out.int16ChannelData, out.frameLength > 0 else { return }
      send(Data(bytes: channel[0], count: Int(out.frameLength) * 2))
    }
    do {
      try engine.start()
      micOn = true
      return "on"
    } catch {
      input.removeTap(onBus: 0)
      configureSession(mic: false)
      return "error: \(error.localizedDescription)"
    }
  }

  private func stopMic() {
    guard micOn else { return }
    engine.inputNode.removeTap(onBus: 0)
    engine.stop()
    micOn = false
    configureSession(mic: false)
  }

  func shutdown() {
    stopMic()
    player?.stop()
    player = nil
    audioQueue.removeAll()
    synth.stopSpeaking(at: .immediate)
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    sessionMicMode = nil
  }
}
