package app.burdamix

import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

/** What Python and the page ask of Android (Python calls these as `jclass("app.burdamix.Platform")`): things only the system can do. */
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

    /** Whether the app may show notifications (Android 13 asks once, and the user may have said no). */
    @JvmStatic
    fun notificationsEnabled(): Boolean = try {
        context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()
    } catch (error: Exception) {
        true
    }

    /** Opens the notification settings of this app, where the user can allow them. */
    @JvmStatic
    fun openNotificationSettings(): Boolean = try {
        context.startActivity(
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        true
    } catch (error: Exception) {
        false
    }

    /**
     * Shows a folder of the phone's storage in the system's file manager. Only the shared storage can be opened (Music/Burdamix):
     * Android does not let a file manager into Android/data, where the app's private folder is. False in that case, or when no app can show it.
     */
    @JvmStatic
    fun openFolder(path: String): Boolean = try {
        val root = Environment.getExternalStorageDirectory().path
        if (!path.startsWith("$root/") && path != root || path.startsWith("$root/Android/")) {
            false
        } else {
            val uri = DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", "primary:" + path.removePrefix(root).trim('/'))
            context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, DocumentsContract.Document.MIME_TYPE_DIR).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        }
    } catch (error: Exception) {
        false
    }

    /** What is on the clipboard, as text ("" when empty). The page cannot read it itself inside a WebView. */
    @JvmStatic
    fun clipboardText(): String = try {
        val clip = (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
        if (clip != null && clip.itemCount > 0) clip.getItemAt(0).coerceToText(context).toString() else ""
    } catch (error: Exception) {
        ""
    }

    /** Puts a text on the clipboard (the code of a playlist). */
    @JvmStatic
    fun copyText(text: String): Boolean = try {
        (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Burdamix", text))
        true
    } catch (error: Exception) {
        false
    }

    /** Opens the system's share sheet with a piece of text (a playlist's code). False when no app can take it. */
    @JvmStatic
    fun shareText(text: String, title: String): Boolean = try {
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text).putExtra(Intent.EXTRA_SUBJECT, title)
        context.startActivity(Intent.createChooser(send, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (error: Exception) {
        false
    }

    /**
     * Opens the share sheet with a file. Only files of the app's own `share` folder in the cache go out (that is what file_paths.xml
     * allows, and what the program writes the cards of the playlists to); anything else is refused.
     */
    @JvmStatic
    fun shareFile(path: String, mime: String, title: String): Boolean {
        return try {
            val file = File(path).canonicalFile
            val root = File(context.cacheDir, "share").canonicalFile
            if (!file.path.startsWith(root.path + File.separator) || !file.isFile) return false
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
            val send = Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri).putExtra(Intent.EXTRA_SUBJECT, title)
            send.clipData = ClipData.newRawUri("", uri)        // the chooser needs this to pass the permission on to the app that is picked
            send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            context.startActivity(Intent.createChooser(send, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
            true
        } catch (error: Exception) {
            false
        }
    }
}
