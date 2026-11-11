package expo.modules.cubeglasses

import android.os.Handler
import android.os.Looper
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString

/**
 * WebSocket to the CubeVision web app (/ws/device).
 *  up:   0x01 + JPEG frame, 0x02 + PCM16 mic audio, JSON text commands
 *  down: JSON events (coaching), handed to [onEvent]
 * Reconnects automatically.
 */
class ServerLink(
    private val onEvent: (String) -> Unit,
    private val onConnection: (Boolean, String) -> Unit,
) {
  companion object {
    private const val FRAME: Byte = 0x01
    private const val AUDIO: Byte = 0x02
    // Drop camera frames if this much is still waiting to go out (keeps latency low).
    private const val MAX_QUEUED_FRAME_BYTES = 256 * 1024L
    private const val MAX_QUEUED_AUDIO_BYTES = 1024 * 1024L
  }

  private val client =
      OkHttpClient.Builder().pingInterval(15, TimeUnit.SECONDS).retryOnConnectionFailure(true).build()
  private val main = Handler(Looper.getMainLooper())
  @Volatile private var socket: WebSocket? = null
  @Volatile private var url: String? = null
  @Volatile private var wanted = false
  @Volatile var connected = false
    private set

  fun connect(newUrl: String) {
    url = newUrl
    wanted = true
    open()
  }

  fun disconnect() {
    wanted = false
    socket?.close(1000, "bye")
    socket = null
    connected = false
    onConnection(false, "Disconnected")
  }

  private fun open() {
    val target = url ?: return
    socket?.cancel()
    val request =
        try {
          Request.Builder().url(target).build()
        } catch (e: IllegalArgumentException) {
          onConnection(false, "Bad server URL")
          return
        }
    onConnection(false, "Connecting to $target…")
    socket = client.newWebSocket(request, Listener())
  }

  private inner class Listener : WebSocketListener() {
    override fun onOpen(webSocket: WebSocket, response: Response) {
      if (webSocket !== socket) return
      connected = true
      onConnection(true, "Connected")
      webSocket.send("""{"type":"hello","device":"android-relay","app_version":"0.1"}""")
    }

    override fun onMessage(webSocket: WebSocket, text: String) {
      if (webSocket === socket) onEvent(text)
    }

    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {}

    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
      webSocket.close(1000, null)
    }

    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = dropped(webSocket, "closed")

    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
        dropped(webSocket, t.message ?: "connection failed")
  }

  private fun dropped(webSocket: WebSocket, why: String) {
    if (webSocket !== socket) return
    connected = false
    onConnection(false, "Server link lost ($why) — retrying…")
    if (wanted) main.postDelayed({ if (wanted && !connected) open() }, 2000)
  }

  fun sendText(json: String): Boolean = socket?.send(json) ?: false

  fun sendFrame(jpeg: ByteArray) = sendBinary(FRAME, jpeg, MAX_QUEUED_FRAME_BYTES)

  fun sendAudio(pcm: ByteArray) = sendBinary(AUDIO, pcm, MAX_QUEUED_AUDIO_BYTES)

  private fun sendBinary(kind: Byte, payload: ByteArray, maxQueued: Long): Boolean {
    val ws = socket ?: return false
    if (!connected || ws.queueSize() > maxQueued) return false
    val data = ByteArray(payload.size + 1)
    data[0] = kind
    System.arraycopy(payload, 0, data, 1, payload.size)
    return ws.send(data.toByteString())
  }

  fun shutdown() {
    disconnect()
    client.dispatcher.executorService.shutdown()
  }
}
