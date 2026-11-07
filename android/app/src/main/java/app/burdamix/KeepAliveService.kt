package app.burdamix

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python

/**
 * Keeps the app alive while it works in the background: downloads (and tag jobs) go on when the user leaves the app for another.
 *
 * Without it Android freezes or kills a process that is not in front, and a download stops half way. This is a foreground service of
 * the "data sync" kind with a visible notification, a partial wake lock (the CPU keeps running with the screen off) and a Wi-Fi lock
 * (the radio does not go to sleep). It does no work itself: Python's threads do. It watches them (`burdamix_host.busy()`) and stops
 * by itself when they finish, so it can never outlive the work, even if the page is gone.
 */
class KeepAliveService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var quietChecks = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra("text").orEmpty().ifEmpty { "Burdamix está trabajando" }
        val notifications = getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL, "Descargas", NotificationManager.IMPORTANCE_LOW).apply { description = "Aviso mientras Burdamix descarga o completa etiquetas" }
        )
        val open = PendingIntent.getActivity(
            this, 1, Intent(this, WebActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_burdamix)
            .setContentTitle("Burdamix")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_PROGRESS)
            .build()
        try {
            if (Build.VERSION.SDK_INT >= 29) startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            else startForeground(ID, notification)
        } catch (error: Exception) {
            Log.w("BurdamixKeepAlive", "could not go to the foreground", error)
        }
        hold()
        quietChecks = 0
        main.removeCallbacks(watch)
        main.postDelayed(watch, CHECK_MS)
        return START_NOT_STICKY
    }

    /** Asks Python whether anything is still running; two quiet checks in a row (a few seconds) and the service stops. */
    private val watch = object : Runnable {
        override fun run() {
            val busy = try {
                Python.getInstance().getModule("burdamix_host").callAttr("busy").toBoolean()
            } catch (error: Exception) {
                false
            }
            quietChecks = if (busy) 0 else quietChecks + 1
            if (quietChecks >= 2) { stopSelf(); return }
            main.postDelayed(this, CHECK_MS)
        }
    }

    private fun hold() {
        if (wakeLock == null) {
            wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Burdamix:work").also { it.setReferenceCounted(false) }
        }
        wakeLock?.let { if (!it.isHeld) it.acquire(3 * 60 * 60 * 1000L) }       // three hours at most: a stuck job must not drain the battery for ever
        try {
            if (wifiLock == null) {
                val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                wifiLock = wifi.createWifiLock(wifiMode(), "Burdamix:work").also { it.setReferenceCounted(false) }
            }
            wifiLock?.let { if (!it.isHeld) it.acquire() }
        } catch (error: Exception) {
            Log.w("BurdamixKeepAlive", "no Wi-Fi lock", error)           // only the radio's sleep mode is not held
        }
    }

    @Suppress("DEPRECATION")
    private fun wifiMode(): Int = if (Build.VERSION.SDK_INT >= 29) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF

    override fun onDestroy() {
        main.removeCallbacks(watch)
        wakeLock?.let { if (it.isHeld) it.release() }
        wifiLock?.let { if (it.isHeld) it.release() }
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "downloads"
        private const val ID = 8
        private const val CHECK_MS = 3000L

        /** Starts (or updates the text of) the service while there is work; asks it to stop when there is none. */
        fun set(context: Context, on: Boolean, text: String) {
            try {
                if (on) context.startForegroundService(Intent(context, KeepAliveService::class.java).putExtra("text", text))
                else context.stopService(Intent(context, KeepAliveService::class.java))
            } catch (error: Exception) {
                Log.w("BurdamixKeepAlive", "could not change the service", error)
            }
        }
    }
}
