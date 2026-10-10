package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Bundle;
import android.util.Log;
import android.view.WindowManager;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The game: starts the Python core (Chaquopy), draws its picture and turns touches into phone keys.
 * Needs the game files in the app's private folder files/game (see android/NOTES.md). While the app is not in the
 * foreground the core is paused (a locked screen freezes the app anyway).
 */
public class MainActivity extends Activity {
    private static final String TAG = "recast";

    private GameView view;
    private final ExecutorService input = Executors.newSingleThreadExecutor(r -> new Thread(r, "recast-input"));
    private volatile PyObject app;                 // the recast_app module once the game has started
    private volatile boolean running = true;
    private volatile boolean resumed = false;      // the activity is in the foreground
    private Thread pump;
    private Thread sound;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (!GameInstaller.isInstalled(this) && !new File(new File(getFilesDir(), "game"), "mod").isDirectory()) {
            startActivity(new Intent(this, SetupActivity.class));      // no game files yet: ask for them first
            finish();
            return;
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        view = new GameView(this);
        view.setKeySink((name, down) -> input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    a.callAttr("key", name, down);
                } catch (Throwable t) {
                    Log.w(TAG, "key failed: " + t);
                }
            }
        }));
        view.setTapSink((x, y) -> input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    a.callAttr("tap", x, y);
                } catch (Throwable t) {
                    Log.w(TAG, "tap failed: " + t);
                }
            }
        }));
        setContentView(view);
        view.setStatus("starting...");
        new Thread(this::startGame, "recast-start").start();
    }

    private void startGame() {
        File game = new File(getFilesDir(), "game");
        File data = new File(getFilesDir(), "data");
        if (!new File(game, "mod").isDirectory()) {
            view.setStatus("game files not found in " + game + " (see android/NOTES.md)");
            return;
        }
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            PyObject module = Python.getInstance().getModule("recast_app");
            module.callAttr("start_game", getApplicationInfo().nativeLibraryDir, game.getAbsolutePath(),
                    data.getAbsolutePath());
            app = module;
            applyLifecycle();                          // the user may have left while the game was still starting
        } catch (Throwable t) {
            Log.e(TAG, "could not start the game", t);
            view.setStatus("could not start: " + t);
            return;
        }
        pump = new Thread(this::pumpFrames, "recast-frames");
        pump.start();
        sound = new Thread(this::pumpSound, "recast-sound");
        sound.start();
    }

    /** Plays the core's sound: asks Python for the next block of mixed samples and writes it to an AudioTrack
     *  (the blocking write paces the loop). Held while the app is not in the foreground. */
    private void pumpSound() {
        final int rate = 22050, frames = 1024;
        AudioTrack track = null;
        long blocks = 0;
        try {
            int min = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
            track = new AudioTrack.Builder()
                    .setAudioAttributes(new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_GAME)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(rate)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                    .setBufferSizeInBytes(Math.max(min * 2, frames * 2 * 4))
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .build();
            while (running) {
                if (!resumed) {
                    if (track.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                        track.pause();
                    }
                    Thread.sleep(100);
                    continue;
                }
                if (track.getPlayState() != AudioTrack.PLAYSTATE_PLAYING) {
                    track.play();
                }
                byte[] block = app.callAttr("audio_read", frames).toJava(byte[].class);
                track.write(block, 0, block.length);
                if (++blocks % 100 == 0) {
                    Log.i(TAG, "audio underruns so far: " + track.getUnderrunCount());
                }
            }
        } catch (InterruptedException e) {
            // closing
        } catch (Throwable t) {
            Log.w(TAG, "sound stopped: " + t);
        } finally {
            if (track != null) {
                track.release();
            }
        }
    }

    /** Fetches each new picture from the core and shows it, and the core's status line about once a second. */
    private void pumpFrames() {
        long last = -1, lastStatus = 0;
        while (running) {
            try {
                PyObject a = app;
                long n = a.callAttr("frame_count").toLong();
                if (n != last) {
                    last = n;
                    view.setFrame(a.callAttr("frame_bytes").toJava(byte[].class));
                }
                long now = System.currentTimeMillis();
                if (now - lastStatus > 1000) {
                    lastStatus = now;
                    String status = a.callAttr("status").toString();
                    view.setStatus(status);
                    Log.i(TAG, "status: " + status);
                    if (status.startsWith("stopped") && !status.contains("ERROR")) {
                        running = false;               // the game asked to exit: close the app (an error stays on screen)
                        runOnUiThread(this::finish);
                        return;
                    }
                }
                Thread.sleep(resumed ? 8 : 250);
            } catch (InterruptedException e) {
                return;
            } catch (Throwable t) {
                Log.w(TAG, "frame pump: " + t);
                try {
                    Thread.sleep(500);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        resumed = false;
        if (view != null) {
            view.releaseAll();
        }
        applyLifecycle();
    }

    /** Tells the core whether the app is in the foreground. Queued on the input thread, and the flag is read when the
     *  task runs, so the last state always wins whatever the order of onPause, onResume and the game starting. */
    private void applyLifecycle() {
        input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    a.callAttr(resumed ? "resume" : "pause");
                } catch (Throwable t) {
                    Log.w(TAG, "pause/resume failed: " + t);
                }
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        applyLifecycle();
    }

    @Override
    protected void onDestroy() {
        running = false;
        if (view == null) {                            // onCreate went to the setup screen
            super.onDestroy();
            return;
        }
        if (pump != null) {
            pump.interrupt();
        }
        if (sound != null) {
            sound.interrupt();
        }
        PyObject a = app;
        if (a != null && isFinishing()) {
            input.execute(() -> a.callAttr("stop"));
        }
        input.shutdown();
        super.onDestroy();
    }
}
