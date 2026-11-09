package app.burdamix

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.webkit.WebViewAssetLoader
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.yausername.ffmpeg.FFmpeg
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * The window of Burdamix: a WebView that shows gui/web (packaged as assets) and a bridge to the program's Python.
 * The page finds `BurdamixAndroid` and gui/web/android.js turns it into the same `window.pywebview.api` the desktop window has.
 * Every call runs on its own pool thread, so a slow one (a search, a download) never holds up the quick ones (the 500 ms event polling).
 */
class WebActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var host: PyObject
    private val pool = Executors.newCachedThreadPool()
    private var fileChooser: ValueCallback<Array<Uri>>? = null     // the page's <input type="file"> waiting for the phone's picker
    private var booted = false              // Python started and the page loading (after the folder of the songs is decided)
    private var waitingStorage = false      // the user is in the system screen that gives access to the shared storage

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        Platform.init(applicationContext)
        host = Python.getInstance().getModule("burdamix_host")
        // The ffmpeg is the executable the youtubedl-android package leaves in nativeLibraryDir; its libraries are unpacked on init.
        FFmpeg.getInstance().init(application)
        chooseMusicFolder()
    }

    /** Music/Burdamix when the app may write there; otherwise ask once (the user may refuse: the private folder then). */
    private fun chooseMusicFolder() {
        val shared = Storage.sharedMusic()
        val prefs = getSharedPreferences("burdamix", MODE_PRIVATE)
        when {
            Storage.canWrite(shared) -> boot(shared)
            prefs.getBoolean(PREF_PRIVATE, false) -> boot(Storage.privateMusic(this))
            else -> AlertDialog.Builder(this)
                .setTitle("Guardar la música en tu teléfono")
                .setMessage("Burdamix puede guardar las canciones en Música/Burdamix para que las veas desde cualquier app de archivos o reproductor. Android lo permite con «Acceso a todos los archivos»; la app solo usa esa carpeta. Si no, quedan dentro de la app, donde no se pueden abrir.")
                .setCancelable(false)
                .setPositiveButton("Dar permiso") { _, _ -> waitingStorage = true; Storage.requestAccess(this, REQUEST_STORAGE) }
                .setNegativeButton("Ahora no") { _, _ -> prefs.edit().putBoolean(PREF_PRIVATE, true).apply(); boot(Storage.privateMusic(this)) }
                .show()
        }
    }

    override fun onResume() {
        super.onResume()
        if (waitingStorage) {                        // back from the system screen of the permission
            waitingStorage = false
            if (!booted) {
                if (Storage.canWrite(Storage.sharedMusic())) boot(Storage.sharedMusic()) else chooseMusicFolder()
            } else if (Storage.canWrite(Storage.sharedMusic())) {
                // Python already runs with the private folder: the app restarts to move the songs (migrate_music) at the next launch.
                Toast.makeText(this, "Listo. Abre Burdamix otra vez y tus canciones pasarán a Música/Burdamix.", Toast.LENGTH_LONG).show()
                finishAndRemoveTask()
                android.os.Process.killProcess(android.os.Process.myPid())
            }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_STORAGE && !booted) {
            waitingStorage = false
            if (Storage.canWrite(Storage.sharedMusic())) boot(Storage.sharedMusic()) else chooseMusicFolder()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun boot(music: File) {
        if (booted) return
        booted = true
        val ffmpegLibs = noBackupFilesDir.resolve("youtubedl-android/packages/ffmpeg/usr/lib").path
        // What the app saved in its private folder before moves to the shared one (nothing to do when both are the same).
        val old = Storage.privateMusic(this)
        host.callAttr("start", filesDir.path, music.path, "${applicationInfo.nativeLibraryDir}/libffmpeg.so",
            "${applicationInfo.nativeLibraryDir}:$ffmpegLibs", cacheDir.resolve("share").path, old.path)

        // Android 13 and later hide notifications until the user allows them: the player's controls need it.
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        }
        // The notification's buttons, the lock screen and the headset come back to the page as words (gui/web/androidmedia.js).
        PlaybackService.onAction = { action ->
            runOnUiThread { if (!isDestroyed) web.evaluateJavascript("window.__burdamixMedia && window.__burdamixMedia(${JSONObject.quote(action)})", null) }
        }

        val assets = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0E110F"))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mediaPlaybackRequiresUserGesture = false
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            settings.useWideViewPort = true           // honour the page's <meta viewport> (width=device-width)
            isVerticalScrollBarEnabled = false         // no desktop-style bars: the page scrolls by touch
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                    assets.shouldInterceptRequest(request.url)

                // Only the app's own pages load here; any other link opens in the system.
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    if (request.url.host == WebViewAssetLoader.DEFAULT_DOMAIN) return false
                    runCatching { startActivity(Intent(Intent.ACTION_VIEW, request.url)) }
                    return true
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    Log.i("BurdamixWeb", "${message.messageLevel()} ${message.sourceId()}:${message.lineNumber()} ${message.message()}")
                    return true
                }

                // <input type="file"> (picking the card of a shared playlist): the system's picker.
                override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                    fileChooser?.onReceiveValue(null)
                    fileChooser = callback
                    return try {
                        @Suppress("DEPRECATION") startActivityForResult(params.createIntent(), REQUEST_FILE)
                        true
                    } catch (error: Exception) {
                        fileChooser = null
                        callback.onReceiveValue(null)
                        false
                    }
                }
            }
            addJavascriptInterface(Bridge(), "BurdamixAndroid")
        }
        setContentView(web)
        web.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}/assets/index.html")
    }

    override fun onDestroy() {
        PlaybackService.onAction = null
        PlaybackService.stop(applicationContext)      // the page is going away: so does the music, and its notification
        pool.shutdownNow()
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }

    @Deprecated("The page decides what back means")
    override fun onBackPressed() {
        // One step back inside the app (close a menu, leave an album, go to the start page...). Only when there is nothing left to go
        // back to does the gesture leave the app: with music playing it goes to the background (the music goes on, with its
        // notification); otherwise the app closes.
        if (!::web.isInitialized) { finish(); return }
        web.evaluateJavascript("(function(){ return !!(window.burdamixBack && window.burdamixBack()); })()") { consumed ->
            if (consumed != "true") {
                if (PlaybackService.playing) moveTaskToBack(true) else finish()
            }
        }
    }

    @Deprecated("The file picker of the page")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_FILE) {
            fileChooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileChooser = null
            return
        }
        @Suppress("DEPRECATION") super.onActivityResult(requestCode, resultCode, data)
    }

    private companion object {
        const val REQUEST_FILE = 41
        const val REQUEST_NOTIFICATIONS = 42
        const val REQUEST_STORAGE = 43
        const val PREF_PRIVATE = "private_music"
    }

    /** The only door between the page and Python (and the phone). Every call comes from a WebView thread, never the UI thread. */
    private inner class Bridge {
        @JavascriptInterface
        fun methods(): String = host.callAttr("methods").toString()

        /** The player's state for the notification and the lock screen (JSON, see gui/web/androidmedia.js). */
        @JavascriptInterface
        fun media(json: String) {
            Log.i("BurdamixMedia", "state from the page: ${json.take(120)}")
            PlaybackService.update(applicationContext, json)
        }

        /** Whether notifications are allowed, and the settings screen where the user can allow them (the player's controls need them). */
        @JavascriptInterface
        fun notificationsEnabled(): Boolean = Platform.notificationsEnabled()

        @JavascriptInterface
        fun openNotificationSettings(): Boolean = Platform.openNotificationSettings()

        /** The songs are in the app's private folder (the user said "not now"): opens the system screen where the permission is given. */
        @JavascriptInterface
        fun requestStorageAccess() = runOnUiThread {
            getSharedPreferences("burdamix", MODE_PRIVATE).edit().remove(PREF_PRIVATE).apply()
            waitingStorage = true
            Storage.requestAccess(this@WebActivity, REQUEST_STORAGE)
        }

        /** While the page has downloads or tag jobs running: keep the app alive in the background (KeepAliveService). */
        @JavascriptInterface
        fun keepAlive(on: Boolean, text: String) = KeepAliveService.set(applicationContext, on, text)

        /** The clipboard, which the page cannot read inside a WebView (the paste button), and writing to it. */
        @JavascriptInterface
        fun clipboardText(): String = Platform.clipboardText()

        @JavascriptInterface
        fun copyText(text: String): Boolean = Platform.copyText(text)

        /** The system's share sheet, for the code or the card of a playlist. */
        @JavascriptInterface
        fun shareText(text: String, title: String): Boolean = Platform.shareText(text, title)

        @JavascriptInterface
        fun shareFile(path: String, mime: String, title: String): Boolean = Platform.shareFile(path, mime, title)

        @JavascriptInterface
        fun call(id: String, name: String, argsJson: String) {
            pool.execute {
                // Whatever happens, the page gets an answer: a promise must never hang.
                val envelope = try {
                    host.callAttr("call", name, argsJson).toString()
                } catch (error: Throwable) {
                    Log.e("Burdamix", "call $name failed", error)
                    JSONObject().put("ok", false)
                        .put("error", JSONObject().put("name", error.javaClass.simpleName).put("message", error.message ?: ""))
                        .toString()
                }
                val script = "window.__burdamixReply(${JSONObject.quote(id)}, ${JSONObject.quote(envelope)})"
                runOnUiThread { if (!isDestroyed) web.evaluateJavascript(script, null) }
            }
        }
    }
}
