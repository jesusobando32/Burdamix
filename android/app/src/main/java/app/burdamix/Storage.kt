package app.burdamix

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import java.io.File

/**
 * Where the songs live. They go in Music/Burdamix of the shared storage, so the user sees them in any file manager and any player;
 * writing there with plain file paths (Python, ffmpeg) needs "Access to all files" on Android 11 and later, and the storage
 * permission before that. If the user says no, the songs stay in the app's private folder (which Android hides from file managers).
 */
object Storage {
    fun sharedMusic(): File = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC), "Burdamix")

    /** The folder the songs used to live in (and live in when the user does not give the permission). */
    fun privateMusic(activity: Activity): File = (activity.getExternalFilesDir(Environment.DIRECTORY_MUSIC) ?: activity.filesDir).resolve("Burdamix")

    /** Whether a file can really be created in the folder: the only honest answer, the permission model differs between versions. */
    fun canWrite(dir: File): Boolean = try {
        dir.mkdirs()
        val probe = File(dir, ".burdamix-prueba")
        probe.writeText("ok")
        probe.delete()
        dir.isDirectory
    } catch (error: Exception) {
        false
    }

    /** Opens the system screen where the user gives the permission (or asks for it, before Android 11). */
    fun requestAccess(activity: Activity, requestCode: Int) {
        if (Build.VERSION.SDK_INT >= 30) {
            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:${activity.packageName}"))
            try {
                activity.startActivity(intent)
            } catch (error: Exception) {
                activity.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        } else {
            activity.requestPermissions(arrayOf(android.Manifest.permission.WRITE_EXTERNAL_STORAGE), requestCode)
        }
    }
}
