package app.burdamix

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.Icon
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * The player's notification, lock screen controls and headset buttons.
 *
 * The WebView plays the songs; Android shows no media controls for a WebView, so this service mirrors what is playing (the page
 * sends the state through `BurdamixAndroid.media`, see gui/web/androidmedia.js) and hands every button back to the page as a word
 * ("toggle", "next", "previous", "shuffle", "seek:<ms>") through [onAction]. It plays nothing itself.
 * It is a foreground service while something plays, which also keeps the app alive when the screen is off or another app is in front.
 * Only framework APIs are used (MediaSession, Notification.MediaStyle), so no library is needed.
 */
class PlaybackService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var session: MediaSession
    private lateinit var notifications: NotificationManager
    private var wakeLock: PowerManager.WakeLock? = null
    private var focus: AudioFocusRequest? = null
    private var noisyReceiver: BroadcastReceiver? = null
    private var foreground = false

    private var title = ""
    private var artist = ""
    private var album = ""
    private var coverUrl = ""
    private var cover: Bitmap? = null
    private var playing = false
    private var positionMs = 0L
    private var durationMs = 0L
    private var shuffle = false
    private var has = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        notifications = getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL, "Reproductor", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Controles de la música: pausa, siguiente, anterior y aleatorio"
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC     // the controls show on the lock screen too
                setShowBadge(false)
            }
        )
        session = MediaSession(this, "Burdamix").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() = act("play")
                override fun onPause() = act("pause")
                override fun onStop() = act("pause")
                override fun onSkipToNext() = act("next")
                override fun onSkipToPrevious() = act("previous")
                override fun onSeekTo(pos: Long) = act("seek:$pos")
                override fun onCustomAction(action: String, extras: android.os.Bundle?) {
                    if (action == ACTION_SHUFFLE) act("shuffle")
                }
            })
            isActive = true
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Started with startForegroundService: Android demands startForeground within seconds, whatever the state turns out to be.
        ensureForeground()
        when (val action = intent?.action) {
            ACTION_TOGGLE -> act("toggle")
            ACTION_NEXT -> act("next")
            ACTION_PREVIOUS -> act("previous")
            ACTION_SHUFFLE -> act("shuffle")
            else -> if (action == null) intent?.getStringExtra("state")?.let { apply(it) }
        }
        return START_NOT_STICKY
    }

    /** Takes the state the page sent ({has, title, artist, album, cover, playing, position, duration, shuffle}). */
    fun apply(json: String) {
        val s = try { JSONObject(json) } catch (error: Exception) { return }
        main.post {
            has = s.optBoolean("has", false)
            if (!has) { stopEverything(); return@post }
            val newCover = s.optString("cover")
            val wasPlaying = playing
            title = s.optString("title")
            artist = s.optString("artist")
            album = s.optString("album")
            playing = s.optBoolean("playing")
            positionMs = s.optLong("position")
            durationMs = s.optLong("duration")
            shuffle = s.optBoolean("shuffle")
            PlaybackService.playing = playing
            if (newCover != coverUrl) { coverUrl = newCover; cover = null; if (newCover.isNotEmpty()) loadCover(newCover) }
            if (playing && !wasPlaying) { takeFocus(); listenForUnplug() } else if (!playing && wasPlaying) { dropFocus(); stopListeningForUnplug() }
            holdCpu(playing)
            render()
        }
    }

    // --- what the system shows -----------------------------------------------------------------------------------------

    private fun render() {
        session.setMetadata(
            MediaMetadata.Builder()
                .putString(MediaMetadata.METADATA_KEY_TITLE, title)
                .putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
                .putString(MediaMetadata.METADATA_KEY_ALBUM, album)
                .putLong(MediaMetadata.METADATA_KEY_DURATION, durationMs)
                .apply { cover?.let { putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, it); putBitmap(MediaMetadata.METADATA_KEY_ART, it) } }
                .build()
        )
        session.setPlaybackState(
            PlaybackState.Builder()
                .setActions(
                    PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_STOP or
                        PlaybackState.ACTION_SKIP_TO_NEXT or PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_SEEK_TO
                )
                .addCustomAction(PlaybackState.CustomAction.Builder(ACTION_SHUFFLE, if (shuffle) "Aleatorio: activado" else "Aleatorio", R.drawable.ic_shuffle).build())
                .setState(if (playing) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED, positionMs, if (playing) 1f else 0f, SystemClock.elapsedRealtime())
                .build()
        )
        val notification = notification()
        if (playing) {
            startForegroundCompat(notification)
        } else {
            // Paused: the notification stays (to resume from it) but can be swiped away, and the service may rest.
            if (foreground) { stopForeground(STOP_FOREGROUND_DETACH); foreground = false }
            notifications.notify(ID, notification)
        }
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, WebActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        fun button(icon: Int, label: String, action: String) =
            Notification.Action.Builder(Icon.createWithResource(this, icon), label, command(action)).build()
        val builder = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_burdamix)
            .setContentTitle(title.ifEmpty { "Burdamix" })
            .setContentText(artist)
            .setSubText(album.ifEmpty { null })
            .setLargeIcon(cover)                       // the cover, big: it is what makes the notification "bigger"
            .setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PUBLIC)   // readable on the lock screen
            .setCategory(Notification.CATEGORY_TRANSPORT)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setOngoing(playing)
            .addAction(button(R.drawable.ic_previous, "Anterior", ACTION_PREVIOUS))
            .addAction(if (playing) button(R.drawable.ic_pause, "Pausa", ACTION_TOGGLE) else button(R.drawable.ic_play, "Reproducir", ACTION_TOGGLE))
            .addAction(button(R.drawable.ic_next, "Siguiente", ACTION_NEXT))
            .addAction(button(R.drawable.ic_shuffle, if (shuffle) "Aleatorio: activado" else "Aleatorio", ACTION_SHUFFLE))
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
        return builder.build()
    }

    private fun command(action: String) = PendingIntent.getService(
        this, action.hashCode(), Intent(this, PlaybackService::class.java).setAction(action), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
    )

    private fun ensureForeground() {
        if (foreground) return
        startForegroundCompat(notification())
    }

    private fun startForegroundCompat(notification: Notification) {
        try {
            if (Build.VERSION.SDK_INT >= 29) startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
            else startForeground(ID, notification)
            foreground = true
        } catch (error: Exception) {
            Log.w("BurdamixMedia", "could not go to the foreground", error)      // the music keeps playing; only the notification is lost
        }
    }

    private fun loadCover(url: String) {
        Thread {
            val bitmap = try {
                val connection = URL(url).openConnection() as HttpURLConnection     // the program's own server on this phone
                connection.connectTimeout = 3000
                connection.readTimeout = 5000
                connection.inputStream.use { decode(it.readBytes()) }
            } catch (error: Exception) {
                null
            }
            main.post { if (url == coverUrl && bitmap != null) { cover = bitmap; if (has) render() } }
        }.start()
    }

    /** The picture at about 512 px: enough for the lock screen, small enough not to waste memory. */
    private fun decode(bytes: ByteArray): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= 512 && bounds.outHeight / (sample * 2) >= 512) sample *= 2
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
    }

    // --- being a good citizen -----------------------------------------------------------------------------------------

    private fun takeFocus() {
        val audio = getSystemService(AudioManager::class.java)
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setOnAudioFocusChangeListener { change ->
                // A call, another player: pause, and do not start again by itself (the user decides).
                if (change == AudioManager.AUDIOFOCUS_LOSS || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) act("pause")
            }
            .build()
        focus = request
        audio.requestAudioFocus(request)
    }

    private fun dropFocus() {
        focus?.let { getSystemService(AudioManager::class.java).abandonAudioFocusRequest(it) }
        focus = null
    }

    private fun listenForUnplug() {
        if (noisyReceiver != null) return
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) = act("pause")      // headphones unplugged: do not blast the speaker
        }
        val filter = IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY)
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED) else registerReceiver(receiver, filter)
        noisyReceiver = receiver
    }

    private fun stopListeningForUnplug() {
        noisyReceiver?.let { runCatching { unregisterReceiver(it) } }
        noisyReceiver = null
    }

    /** With the screen off, Android may put the CPU to sleep and the music would stutter: keep it awake while playing. */
    private fun holdCpu(on: Boolean) {
        val lock = wakeLock ?: getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Burdamix:playback").also {
            it.setReferenceCounted(false)
            wakeLock = it
        }
        if (on && !lock.isHeld) lock.acquire(6 * 60 * 60 * 1000L) else if (!on && lock.isHeld) lock.release()
    }

    private fun act(action: String) {
        onAction?.invoke(action)
    }

    fun stopEverything() {
        has = false
        playing = false
        PlaybackService.playing = false
        dropFocus()
        stopListeningForUnplug()
        holdCpu(false)
        stopForeground(STOP_FOREGROUND_REMOVE)
        foreground = false
        notifications.cancel(ID)
        stopSelf()
    }

    override fun onDestroy() {
        stopListeningForUnplug()
        dropFocus()
        holdCpu(false)
        session.isActive = false
        session.release()
        if (instance === this) instance = null
        PlaybackService.playing = false
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "playback"
        private const val ID = 7
        private const val ACTION_TOGGLE = "app.burdamix.action.TOGGLE"
        private const val ACTION_NEXT = "app.burdamix.action.NEXT"
        private const val ACTION_PREVIOUS = "app.burdamix.action.PREVIOUS"
        private const val ACTION_SHUFFLE = "app.burdamix.action.SHUFFLE"

        @Volatile private var instance: PlaybackService? = null

        /** True while a song is playing: the back gesture then leaves the music playing (WebActivity). */
        @Volatile var playing = false
            private set

        /** Where the buttons go: WebActivity hands them to the page. */
        @Volatile var onAction: ((String) -> Unit)? = null

        /** The page's new state. While the service runs it takes it at once; otherwise it is started (the app is in front when music starts). */
        fun update(context: Context, json: String) {
            val running = instance
            if (running != null) { running.apply(json); return }
            if (!JSONObject(json).optBoolean("has", false)) return          // nothing is playing and nothing to show: do not start a service for that
            try {
                context.startForegroundService(Intent(context, PlaybackService::class.java).putExtra("state", json))
            } catch (error: Exception) {
                Log.w("BurdamixMedia", "could not start the service", error)
            }
        }

        fun stop(context: Context) {
            instance?.let { it.main.post { it.stopEverything() } } ?: context.stopService(Intent(context, PlaybackService::class.java))
        }
    }
}
