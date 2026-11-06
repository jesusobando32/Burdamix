package app.burdamix

import android.content.Context
import android.content.Intent
import android.net.Uri

/** What Python asks of Android (it calls these as `jclass("app.burdamix.Platform")`): things only the system can do. */
object Platform {
    private lateinit var context: Context

    fun init(applicationContext: Context) {
        context = applicationContext
    }

    /** Opens a web link in the user's browser. Returns false when nothing can open it. */
    @JvmStatic
    fun openUrl(url: String): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (error: Exception) {
        false
    }
}
