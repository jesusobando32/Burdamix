package app.burdamix

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.text.method.ScrollingMovementMethod
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.chaquo.python.Python
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import java.io.File
import kotlin.concurrent.thread

/**
 * The test of the phone (step one of the mobile version). Two ways of downloading a song and making an MP3 are tried on the device
 * itself, with no computer:
 *  - "Python": yt-dlp running inside the app through Chaquopy, the way the desktop program works today (burdamix_spike.py);
 *  - "Motor Kotlin": the youtubedl-android library, which carries its own yt-dlp, Python and ffmpeg.
 * The screen says what each stage did, so a failure shows exactly where it stopped. Nothing here is the final interface.
 */
class MainActivity : Activity() {
    private lateinit var log: TextView
    private lateinit var url: EditText
    private lateinit var buttons: List<Button>

    // A short public video, only used to see whether the phone can do the whole job.
    private val sample = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildScreen()
        say("Burdamix · prueba en el teléfono\nCarpeta de salida: ${outDir().absolutePath}\n")
        // The libraries unpack their binaries the first time: away from the screen thread.
        thread(name = "init-engines") {
            try {
                YoutubeDL.getInstance().init(application)
                FFmpeg.getInstance().init(application)
                say("✔ youtubedl-android y ffmpeg listos")
            } catch (error: Throwable) {
                say("✘ No pude preparar youtubedl-android/ffmpeg: ${error.javaClass.simpleName}: ${error.message}")
            }
            val found = findFfmpeg()
            say(if (found != null) "ffmpeg encontrado en: $found" else "ffmpeg: no encontré ningún ejecutable")
            runOnUiThread { buttons.forEach { it.isEnabled = true } }
        }
    }

    private fun outDir(): File = (getExternalFilesDir(null) ?: filesDir).resolve("prueba").also { it.mkdirs() }

    /** The library does not say where it leaves ffmpeg, so the test looks for it and reports what it finds. */
    private fun findFfmpeg(): String? {
        val roots = listOfNotNull(noBackupFilesDir, filesDir, File(applicationInfo.nativeLibraryDir))
        return roots.asSequence()
            .flatMap { it.walkTopDown().asSequence() }
            .firstOrNull { it.isFile && (it.name == "ffmpeg" || it.name == "libffmpeg.so") && it.canExecute() }
            ?.absolutePath
    }

    private fun runPython() = work("Python (Chaquopy + yt-dlp)") {
        val module = Python.getInstance().getModule("burdamix_spike")
        val result = module.callAttr("probe", url.text.toString().trim(), outDir().absolutePath, findFfmpeg() ?: "")
        say(module.callAttr("render", result).toString())
    }

    private fun runKotlin() = work("Motor Kotlin (youtubedl-android)") {
        val request = YoutubeDLRequest(url.text.toString().trim())
        request.addOption("-x")
        request.addOption("--audio-format", "mp3")
        request.addOption("-o", outDir().absolutePath + "/kotlin-%(title)s.%(ext)s")
        val response = YoutubeDL.getInstance().execute(request)
        val made = outDir().listFiles { f -> f.name.startsWith("kotlin-") && f.extension == "mp3" }?.joinToString { "${it.name} (${it.length() / 1024} KB)" }
        say("✔ yt-dlp terminó con código ${response.exitCode}. Archivos: ${made ?: "ninguno"}")
    }

    /** Runs one test in the background and always comes back with a line: a failed test is an answer, not a crash. */
    private fun work(name: String, body: () -> Unit) {
        runOnUiThread { buttons.forEach { it.isEnabled = false } }
        say("\n▶ $name")
        thread(name = "test") {
            try {
                body()
            } catch (error: Throwable) {
                Log.e("Burdamix", "test failed", error)
                say("✘ ${error.javaClass.simpleName}: ${error.message}")
            } finally {
                runOnUiThread { buttons.forEach { it.isEnabled = true } }
            }
        }
    }

    private fun say(text: String) {
        Log.i("Burdamix", text)
        runOnUiThread { log.append(text + "\n") }
    }

    private fun buildScreen() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0A0D0B"))
            setPadding(pad, pad * 2, pad, pad)
        }
        url = EditText(this).apply {
            setText(sample); setTextColor(Color.WHITE); setHintTextColor(Color.GRAY); hint = "Enlace del video"
            setSingleLine(true)
        }
        val python = button("Probar: Python (como el escritorio)") { runPython() }
        val kotlin = button("Probar: motor Kotlin") { runKotlin() }
        buttons = listOf(python, kotlin).onEach { it.isEnabled = false }
        log = TextView(this).apply {
            setTextColor(Color.parseColor("#EAF0EB")); typeface = Typeface.MONOSPACE; textSize = 12f
            setTextIsSelectable(true); movementMethod = ScrollingMovementMethod()
        }
        column.addView(url, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        buttons.forEach { column.addView(it, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)) }
        column.addView(ScrollView(this).apply { addView(log) }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(column)
    }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; gravity = Gravity.CENTER; setOnClickListener { onClick() }
    }
}
