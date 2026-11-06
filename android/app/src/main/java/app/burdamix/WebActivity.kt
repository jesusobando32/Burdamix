package app.burdamix

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader
import com.chaquo.python.PyObject
import com.chaquo.python.Python
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

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        host = Python.getInstance().getModule("burdamix_host")

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
            }
            addJavascriptInterface(Bridge(), "BurdamixAndroid")
        }
        setContentView(web)
        web.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}/assets/index.html")
    }

    override fun onDestroy() {
        pool.shutdownNow()
        web.destroy()
        super.onDestroy()
    }

    @Deprecated("Back goes through the page's history first")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    /** The only door between the page and Python. Both calls come from a WebView thread, never the UI thread. */
    private inner class Bridge {
        @JavascriptInterface
        fun methods(): String = host.callAttr("methods").toString()

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
