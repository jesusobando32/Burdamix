package app.burdamix

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
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
import androidx.webkit.WebViewAssetLoader
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.yausername.ffmpeg.FFmpeg
import org.json.JSONObject
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

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        Platform.init(applicationContext)
        host = Python.getInstance().getModule("burdamix_host")
        // The ffmpeg is the executable the youtubedl-android package leaves in nativeLibraryDir; its libraries are unpacked on init.
        FFmpeg.getInstance().init(application)
        val ffmpegLibs = noBackupFilesDir.resolve("youtubedl-android/packages/ffmpeg/usr/lib").path
        val music = (getExternalFilesDir(Environment.DIRECTORY_MUSIC) ?: filesDir).resolve("Burdamix")
        host.callAttr("start", filesDir.path, music.path, "${applicationInfo.nativeLibraryDir}/libffmpeg.so",
            "${applicationInfo.nativeLibraryDir}:$ffmpegLibs", cacheDir.resolve("share").path)

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
        web.destroy()
        super.onDestroy()
    }

    @Deprecated("The page decides what back means")
    override fun onBackPressed() {
        // One step back inside the app (close a menu, leave an album, go to the start page...). Only when there is nothing left to go
        // back to does the gesture leave the app: with music playing it goes to the background (the music goes on, with its
        // notification); otherwise the app closes.
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
