package expo.modules.cubeglasses

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/** Converts the DAT SDK's decoded I420 frames to JPEG. */
object FrameEncoder {
  fun i420ToJpeg(buffer: ByteBuffer, width: Int, height: Int, quality: Int): ByteArray? {
    if (width <= 0 || height <= 0) return null
    val ySize = width * height
    val uvSize = ySize / 4
    val needed = ySize + 2 * uvSize
    val src = buffer.duplicate()
    src.rewind()
    if (src.remaining() < needed) return null
    val i420 = ByteArray(needed)
    src.get(i420)

    // I420 (Y, U, V planes) -> NV21 (Y, interleaved V/U), which YuvImage understands.
    val nv21 = ByteArray(needed)
    System.arraycopy(i420, 0, nv21, 0, ySize)
    val uStart = ySize
    val vStart = ySize + uvSize
    var o = ySize
    for (i in 0 until uvSize) {
      nv21[o++] = i420[vStart + i]
      nv21[o++] = i420[uStart + i]
    }
    val out = ByteArrayOutputStream(needed / 4)
    YuvImage(nv21, ImageFormat.NV21, width, height, null)
        .compressToJpeg(Rect(0, 0, width, height), quality, out)
    return out.toByteArray()
  }
}
