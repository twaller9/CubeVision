package expo.modules.cubeglasses

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import androidx.core.content.ContextCompat
import android.util.Base64
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.VideoFrame
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.types.WearablesError
import com.meta.wearable.dat.mockdevice.MockDeviceKit
import com.meta.wearable.dat.mockdevice.api.GlassesModel
import com.meta.wearable.dat.mockdevice.api.MockDeviceKitConfig
import com.meta.wearable.dat.mockdevice.api.MockGlasses
import com.meta.wearable.dat.mockdevice.api.camera.CameraFacing
import kotlin.coroutines.resume
import com.meta.wearable.dat.camera.types.StreamState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext

/**
 * Wraps the Meta Wearables Device Access Toolkit: registration, camera permission,
 * device session and the camera stream. Each decoded frame is JPEG-encoded and handed to
 * [onJpeg] (throttled). No cube logic lives on the phone.
 */
class GlassesController(
    private val context: Context,
    private val scope: CoroutineScope,
    private val emit: (String, Map<String, Any?>) -> Unit,
    private val onJpeg: (ByteArray) -> Unit,
) {
  companion object {
    private const val TAG = "CubeGlasses"
    private const val PREVIEW_INTERVAL_MS = 700L
  }

  private var initialized = false
  private var session: DeviceSession? = null
  private var camera: Camera? = null
  private val jobs = mutableListOf<Job>()
  private var mockGlasses: MockGlasses? = null

  @Volatile var sendIntervalMs = 200L
  @Volatile private var lastSent = 0L
  @Volatile private var lastPreview = 0L

  // ------------------------------------------------------------------ setup

  fun initialize(): String {
    if (initialized) return "ok"
    if (ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) !=
        PackageManager.PERMISSION_GRANTED) {
      return "error: Bluetooth permission is needed to talk to the glasses"
    }
    val error = Wearables.initialize(context).errorOrNull()
    if (error != null && error != WearablesError.ALREADY_INITIALIZED) {
      return "error: ${error.description}"
    }
    initialized = true
    scope.launch {
      Wearables.registrationState.collect { emit("onRegistration", mapOf("state" to it.name)) }
    }
    scope.launch { Wearables.devices.collect { emit("onDevices", mapOf("count" to it.size)) } }
    scope.launch {
      Wearables.registrationErrorStream.collect {
        status("Registration error: ${it.description}")
      }
    }
    return "ok"
  }

  fun startRegistration(activity: ComponentActivity) = Wearables.startRegistration(activity)

  fun startUnregistration(activity: ComponentActivity) = Wearables.startUnregistration(activity)

  /** Asks the Meta AI app for glasses-camera access if not already granted. */
  suspend fun requestCameraPermission(activity: ComponentActivity): String {
    val current = Wearables.checkPermissionStatus(Permission.CAMERA).getOrNull()
    if (current == PermissionStatus.Granted) return "granted"
    return withContext(Dispatchers.Main) {
      suspendCancellableCoroutine { cont ->
        var launcher: ActivityResultLauncher<Permission>? = null
        launcher =
            activity.activityResultRegistry.register(
                "cubeglasses-camera-${SystemClock.elapsedRealtimeNanos()}",
                Wearables.RequestPermissionContract(),
            ) { result ->
              val status = result.getOrDefault(PermissionStatus.Denied)
              launcher?.unregister()
              if (cont.isActive) cont.resume(if (status == PermissionStatus.Granted) "granted" else "denied")
            }
        cont.invokeOnCancellation { launcher.unregister() }
        launcher.launch(Permission.CAMERA)
      }
    }
  }

  /** Mock glasses: the phone's back camera pretends to be the glasses camera. */
  fun setMockGlasses(enabled: Boolean): String {
    val kit = MockDeviceKit.getInstance(context)
    return if (enabled) {
      if (!kit.isEnabled) {
        kit.enable(MockDeviceKitConfig(initiallyRegistered = true, initialPermissionsGranted = true))
      }
      if (mockGlasses == null) {
        val glasses =
            kit.pairGlasses(GlassesModel.RAYBAN_META).getOrNull()
                ?: return "error: could not create mock glasses"
        glasses.powerOn()
        glasses.unfold()
        glasses.don()
        glasses.services.camera.setCameraFeed(CameraFacing.BACK)
        mockGlasses = glasses
      }
      "ok"
    } else {
      stopStreaming()
      mockGlasses?.let { kit.unpairDevice(it) }
      mockGlasses = null
      if (kit.isEnabled) kit.disable()
      "ok"
    }
  }

  // ------------------------------------------------------------------ streaming

  fun startStreaming(fps: Int): String {
    // A tap on "Start" always begins from a clean slate, even if an old session is stuck.
    if (session != null) stopStreaming()
    sendIntervalMs = (1000.0 / fps.coerceIn(1, 15)).toLong()
    var result = "ok"
    Wearables.createSession(AutoDeviceSelector())
        .onSuccess { created ->
          session = created
          emit("onStream", mapOf("state" to "STARTING")) // lets the UI show "Stop" right away
          // UNDISPATCHED so we really subscribe before start(): errors aren't replayed.
          jobs +=
              scope.launch(start = CoroutineStart.UNDISPATCHED) {
                created.errors.collect { status("Glasses: ${it.description}") }
              }
          jobs +=
              scope.launch(start = CoroutineStart.UNDISPATCHED) {
                created.state.collect { state ->
                  status("Glasses session: ${state.name.lowercase()}")
                  when (state) {
                    DeviceSessionState.STARTED -> if (camera == null) startCamera(created)
                    // A new session starts IDLE, so STOPPED always means it ended.
                    DeviceSessionState.STOPPED -> if (session === created) cleanup()
                    else -> {}
                  }
                }
              }
          created.start()
          if (session === created && created.state.value == DeviceSessionState.IDLE) {
            // Preflight failed (glasses not connected) — start() returned without starting.
            result = "error: glasses not connected — open the Meta AI app and check they're paired and on"
            status(result.removePrefix("error: "))
            stopStreaming()
          }
        }
        .onFailure { error, _ ->
          result = "error: ${error.description}"
          status("Couldn't connect to glasses: ${error.description}")
        }
    return result
  }

  private fun startCamera(s: DeviceSession) {
    s.addCamera(
            StreamConfiguration(
                videoQuality = VideoQuality.MEDIUM, // 504x896: enough pixels per sticker
                frameRate = 15,
                compressVideo = false, // decoded I420 frames we can JPEG-encode
            ),
        )
        .onSuccess { cam ->
          camera = cam
          val stream = cam.stream
          jobs += scope.launch(Dispatchers.Default) { stream.videoStream.collect { onFrame(it) } }
          jobs +=
              scope.launch(start = CoroutineStart.UNDISPATCHED) {
                // The flow replays STOPPED on subscribe, so only a STOPPED/CLOSED after the
                // stream was active means it ended (glasses folded, too hot, battery, ...).
                var active = false
                stream.state.collect { st ->
                  emit("onStream", mapOf("state" to st.name))
                  val terminal = st == StreamState.STOPPED || st == StreamState.CLOSED
                  if (!terminal) active = true
                  else if (active && camera === cam) {
                    active = false
                    status("Glasses camera stopped")
                    stopStreaming()
                  }
                }
              }
          jobs += scope.launch { stream.errorStream.collect { status("Camera: ${it.description}") } }
          stream.start().onFailure { error, _ ->
            status("Camera failed to start: ${error.description}")
            stopStreaming()
          }
        }
        .onFailure { error, _ ->
          status("Couldn't open glasses camera: ${error.description}")
          stopStreaming()
        }
  }

  private fun onFrame(frame: VideoFrame) {
    if (frame.isCompressed) return
    val now = SystemClock.elapsedRealtime()
    val send = now - lastSent >= sendIntervalMs
    val preview = now - lastPreview >= PREVIEW_INTERVAL_MS
    if (!send && !preview) return
    val jpeg =
        try {
          FrameEncoder.i420ToJpeg(frame.buffer, frame.width, frame.height, 75)
        } catch (t: Throwable) {
          Log.w(TAG, "frame encode failed", t)
          null
        } ?: return
    if (send) {
      lastSent = now
      onJpeg(jpeg)
    }
    if (preview) {
      lastPreview = now
      emit(
          "onPreview",
          mapOf(
              "jpeg" to Base64.encodeToString(jpeg, Base64.NO_WRAP),
              "width" to frame.width,
              "height" to frame.height,
          ),
      )
    }
  }

  fun stopStreaming() {
    camera?.stop()
    session?.stop()
    cleanup()
  }

  private fun cleanup() {
    val old = jobs.toList()
    jobs.clear()
    camera = null
    session = null
    emit("onStream", mapOf("state" to "STOPPED"))
    old.forEach { it.cancel() }
  }

  private fun status(text: String) {
    Log.i(TAG, text)
    emit("onStatus", mapOf("status" to text))
  }
}
