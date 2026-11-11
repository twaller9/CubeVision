package expo.modules.cubeglasses

import android.view.WindowManager
import androidx.activity.ComponentActivity
import expo.modules.kotlin.functions.Coroutine
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The phone side of CubeVision: glasses camera -> web app, web app -> glasses speakers,
 * optional glasses mic -> web app. JS only draws the UI.
 */
class CubeGlassesModule : Module() {
  private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

  private val context
    get() = requireNotNull(appContext.reactContext) { "React context not ready" }.applicationContext

  private val link by lazy {
    ServerLink(
        onEvent = { text -> scope.launch { handleServerEvent(text) } },
        onConnection = { connected, status ->
          sendEvent("onServer", mapOf("connected" to connected, "status" to status))
        },
    )
  }

  private val audio by lazy { AudioBridge(context) { pcm -> link.sendAudio(pcm) } }

  private val glasses by lazy {
    GlassesController(
        context = context,
        scope = scope,
        emit = { name, body -> sendEvent(name, body) },
        onJpeg = { jpeg -> link.sendFrame(jpeg) },
    )
  }

  private fun activity(): ComponentActivity =
      appContext.currentActivity as? ComponentActivity
          ?: throw IllegalStateException("No foreground activity")

  private fun handleServerEvent(text: String) {
    val event =
        try {
          JSONObject(text)
        } catch (_: Exception) {
          return
        }
    audio.onServerEvent(event)
    // Audio stays on the native side; JS only needs the text.
    event.remove("audio_b64")
    sendEvent("onServerEvent", mapOf("json" to event.toString()))
  }

  override fun definition() = ModuleDefinition {
    Name("CubeGlasses")

    Events("onRegistration", "onDevices", "onStatus", "onStream", "onPreview", "onServer", "onServerEvent")

    AsyncFunction("initialize") { glasses.initialize() }.runOnQueue(Queues.MAIN)

    AsyncFunction("startRegistration") { glasses.startRegistration(activity()) }.runOnQueue(Queues.MAIN)

    AsyncFunction("startUnregistration") { glasses.startUnregistration(activity()) }.runOnQueue(Queues.MAIN)

    AsyncFunction("requestCameraPermission") Coroutine { -> glasses.requestCameraPermission(activity()) }

    AsyncFunction("setMockGlasses") { enabled: Boolean -> glasses.setMockGlasses(enabled) }.runOnQueue(Queues.MAIN)

    AsyncFunction("startStreaming") { fps: Int -> glasses.startStreaming(fps) }.runOnQueue(Queues.MAIN)

    AsyncFunction("stopStreaming") { glasses.stopStreaming() }.runOnQueue(Queues.MAIN)

    AsyncFunction("connect") { url: String -> link.connect(url) }

    AsyncFunction("disconnect") { link.disconnect() }

    AsyncFunction("send") { json: String -> link.sendText(json) }

    AsyncFunction("setSpeakFallback") { on: Boolean -> audio.speakTextFallback = on }

    AsyncFunction("setMicForwarding") { on: Boolean -> audio.setMicForwarding(on) }

    AsyncFunction("setKeepScreenOn") { on: Boolean ->
      val window = appContext.currentActivity?.window ?: return@AsyncFunction
      if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
      else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }.runOnQueue(Queues.MAIN)

    Function("getPref") { key: String ->
      context.getSharedPreferences("cubeglasses", android.content.Context.MODE_PRIVATE).getString(key, null)
    }

    Function("setPref") { key: String, value: String ->
      context.getSharedPreferences("cubeglasses", android.content.Context.MODE_PRIVATE)
          .edit().putString(key, value).apply()
    }

    OnDestroy {
      try {
        glasses.stopStreaming()
      } catch (_: Throwable) {}
      link.shutdown()
      audio.shutdown()
      scope.cancel()
    }
  }
}
