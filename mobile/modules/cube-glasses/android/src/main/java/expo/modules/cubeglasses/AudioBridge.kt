package expo.modules.cubeglasses

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.speech.tts.TextToSpeech
import android.util.Base64
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.File
import java.util.Locale
import org.json.JSONObject

/**
 * Plays what the web app says on the glasses (they're a Bluetooth audio device), and can
 * forward the glasses mic to the web app for the speech-to-speech side. No speech logic here.
 */
class AudioBridge(private val context: Context, private val sendMic: (ByteArray) -> Unit) :
    TextToSpeech.OnInitListener {
  companion object {
    private const val TAG = "CubeGlassesAudio"
    private const val SAMPLE_RATE = 16_000
    /** Event types whose speech replaces anything still queued. */
    private val INTERRUPTING = setOf("welcome", "reset", "solution", "progress", "off_track", "lost")
  }

  /** Speak the "say" text on the phone when the server didn't send audio. */
  @Volatile var speakTextFallback = true

  private val tts = TextToSpeech(context.applicationContext, this)
  @Volatile private var ttsReady = false
  private var player: MediaPlayer? = null
  private var playingFile: File? = null
  private val audioQueue = ArrayDeque<File>()
  private val audioManager = context.getSystemService(AudioManager::class.java)

  @Volatile private var micRunning = false
  private var micThread: Thread? = null

  private val speechAttrs =
      AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_ASSISTANT)
          .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
          .build()

  // While the glasses mic is open the Bluetooth link is in call (SCO) mode, so speech must
  // use the voice-communication route or it plays on the phone speaker instead.
  private val commAttrs =
      AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
          .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
          .build()

  private fun currentAttrs() = if (micRunning) commAttrs else speechAttrs

  override fun onInit(status: Int) {
    ttsReady = status == TextToSpeech.SUCCESS
    if (ttsReady) {
      tts.language = Locale.US
      tts.setSpeechRate(1.05f)
      tts.setAudioAttributes(currentAttrs())
    }
  }

  /**
   * Called on the main thread with each server event. Lines are queued so one burst of events
   * ("I found a solution…" then the first step) is spoken in full, while events that start
   * something new (next move, reset, re-plan) drop whatever is stale.
   */
  fun onServerEvent(event: JSONObject) {
    val audio = event.optString("audio_b64", "")
    val say = event.optString("say", "")
    val interrupt = event.optString("type") in INTERRUPTING
    if (audio.isNotEmpty()) {
      enqueueAudio(audio, event.optString("audio_format", "mp3"), interrupt)
    } else if (say.isNotEmpty() && speakTextFallback && ttsReady) {
      val mode = if (interrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
      tts.speak(say, mode, null, "cv-${System.nanoTime()}")
    }
  }

  private fun enqueueAudio(b64: String, format: String, interrupt: Boolean) {
    try {
      if (interrupt) {
        tts.stop()
        stopPlayer()
        audioQueue.forEach { it.delete() }
        audioQueue.clear()
      }
      val ext = format.filter { it.isLetterOrDigit() }.ifEmpty { "mp3" }
      val file = File(context.cacheDir, "say-${System.nanoTime()}.$ext")
      file.writeBytes(Base64.decode(b64, Base64.DEFAULT))
      audioQueue.addLast(file)
      if (player == null) playNext()
    } catch (t: Throwable) {
      Log.w(TAG, "audio decode failed", t)
    }
  }

  private fun playNext() {
    while (audioQueue.isNotEmpty()) {
      val file = audioQueue.removeFirst()
      try {
        val mp = MediaPlayer()
        val done = { p: MediaPlayer ->
          p.release()
          file.delete()
          if (player === p) {
            player = null
            playingFile = null
            playNext()
          }
        }
        mp.setAudioAttributes(currentAttrs())
        mp.setDataSource(file.path)
        mp.setOnCompletionListener { done(it) }
        mp.setOnErrorListener { p, _, _ ->
          done(p)
          true
        }
        mp.prepare()
        player = mp
        playingFile = file
        mp.start()
        return
      } catch (t: Throwable) {
        Log.w(TAG, "audio playback failed", t)
        file.delete()
      }
    }
  }

  private fun stopPlayer() {
    player?.release()
    player = null
    playingFile?.delete()
    playingFile = null
  }

  // ------------------------------------------------------------------ mic forwarding

  @SuppressLint("MissingPermission")
  fun setMicForwarding(on: Boolean): String {
    if (!on) {
      stopMic()
      return "off"
    }
    if (micRunning) return "on"
    if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.RECORD_AUDIO) !=
        PackageManager.PERMISSION_GRANTED) {
      return "no-permission"
    }
    // Prefer the glasses' Bluetooth mic when it's available.
    audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
    audioManager.availableCommunicationDevices
        .firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
        ?.let { audioManager.setCommunicationDevice(it) }

    val minBuf =
        AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    val recorder =
        AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, 6400),
        )
    if (recorder.state != AudioRecord.STATE_INITIALIZED) {
      recorder.release()
      audioManager.clearCommunicationDevice()
      audioManager.mode = AudioManager.MODE_NORMAL
      return "error: microphone unavailable"
    }
    micRunning = true
    if (ttsReady) tts.setAudioAttributes(commAttrs)
    micThread =
        Thread({
              try {
                recorder.startRecording()
                val buf = ByteArray(3200) // 100 ms of 16 kHz mono PCM16
                while (micRunning) {
                  val n = recorder.read(buf, 0, buf.size)
                  if (n > 0) sendMic(buf.copyOf(n))
                }
              } finally {
                try { recorder.stop() } catch (_: Throwable) {}
                recorder.release()
              }
            }, "cubeglasses-mic")
            .apply { start() }
    return "on"
  }

  private fun stopMic() {
    val wasRunning = micRunning
    micRunning = false
    micThread?.join(500)
    micThread = null
    if (wasRunning) {
      audioManager.clearCommunicationDevice()
      audioManager.mode = AudioManager.MODE_NORMAL
      if (ttsReady) tts.setAudioAttributes(speechAttrs)
    }
  }

  fun shutdown() {
    stopMic()
    stopPlayer()
    audioQueue.forEach { it.delete() }
    audioQueue.clear()
    tts.stop()
    tts.shutdown()
  }
}
