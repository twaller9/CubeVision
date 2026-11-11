import Foundation

/// WebSocket to the CubeVision web app (/ws/device).
///  up:   0x01 + JPEG frame, 0x02 + PCM16 mic audio, JSON text commands
///  down: JSON events (coaching), handed to `onEvent`
/// All state lives on the main queue. Reconnects automatically.
final class ServerLink: NSObject, URLSessionWebSocketDelegate {
  var onEvent: (String) -> Void = { _ in }
  var onConnection: (Bool, String) -> Void = { _, _ in }

  private static let frameKind: UInt8 = 0x01
  private static let audioKind: UInt8 = 0x02
  /// Drop camera frames while this many are still in flight (keeps latency low).
  private static let maxFramesInFlight = 2

  private lazy var urlSession = URLSession(configuration: .default, delegate: self, delegateQueue: .main)
  private var task: URLSessionWebSocketTask?
  private var url: URL?
  private var wanted = false
  private var connected = false
  private var framesInFlight = 0

  func connect(_ urlString: String) {
    DispatchQueue.main.async {
      guard let url = URL(string: urlString), url.scheme == "ws" || url.scheme == "wss" else {
        self.onConnection(false, "Bad server URL (use ws://host:8000/ws/device)")
        return
      }
      self.url = url
      self.wanted = true
      self.open()
    }
  }

  func disconnect() {
    DispatchQueue.main.async {
      self.wanted = false
      self.task?.cancel(with: .goingAway, reason: nil)
      self.task = nil
      self.connected = false
      self.onConnection(false, "Disconnected")
    }
  }

  private func open() {
    guard let url else { return }
    task?.cancel(with: .goingAway, reason: nil)
    connected = false
    framesInFlight = 0
    onConnection(false, "Connecting to \(url.absoluteString)…")
    let newTask = urlSession.webSocketTask(with: url)
    task = newTask
    newTask.resume()
  }

  // MARK: URLSessionWebSocketDelegate (delivered on the main queue)

  func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
    guard webSocketTask === task else { return }
    connected = true
    onConnection(true, "Connected")
    webSocketTask.send(.string(#"{"type":"hello","device":"ios-relay","app_version":"0.1"}"#)) { _ in }
    receive(on: webSocketTask)
  }

  func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                  didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
    dropped(webSocketTask, why: "closed")
  }

  func urlSession(_ session: URLSession, task finished: URLSessionTask, didCompleteWithError error: Error?) {
    guard let ws = finished as? URLSessionWebSocketTask else { return }
    dropped(ws, why: error?.localizedDescription ?? "connection ended")
  }

  private func receive(on ws: URLSessionWebSocketTask) {
    ws.receive { [weak self] result in
      DispatchQueue.main.async {
        guard let self, ws === self.task else { return }
        switch result {
        case .success(.string(let text)):
          self.onEvent(text)
          self.receive(on: ws)
        case .success:
          self.receive(on: ws)
        case .failure(let error):
          self.dropped(ws, why: error.localizedDescription)
        }
      }
    }
  }

  private func dropped(_ ws: URLSessionWebSocketTask, why: String) {
    guard ws === task, wanted || connected else { return }
    connected = false
    task = nil
    onConnection(false, "Server link lost (\(why)) — retrying…")
    guard wanted else { return }
    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
      guard let self, self.wanted, !self.connected, self.task == nil else { return }
      self.open()
    }
  }

  // MARK: Sending (safe from any thread)

  func sendText(_ json: String) {
    DispatchQueue.main.async {
      self.task?.send(.string(json)) { _ in }
    }
  }

  func sendFrame(_ jpeg: Data) { sendBinary(kind: Self.frameKind, payload: jpeg, droppable: true) }

  func sendAudio(_ pcm: Data) { sendBinary(kind: Self.audioKind, payload: pcm, droppable: false) }

  private func sendBinary(kind: UInt8, payload: Data, droppable: Bool) {
    DispatchQueue.main.async {
      guard let ws = self.task, self.connected else { return }
      if droppable {
        if self.framesInFlight >= Self.maxFramesInFlight { return }
        self.framesInFlight += 1
      }
      var data = Data([kind])
      data.append(payload)
      ws.send(.data(data)) { [weak self] _ in
        guard droppable else { return }
        DispatchQueue.main.async {
          guard let self, ws === self.task else { return }
          self.framesInFlight = max(0, self.framesInFlight - 1)
        }
      }
    }
  }

  func shutdown() {
    disconnect()
    DispatchQueue.main.async { self.urlSession.invalidateAndCancel() }
  }
}
