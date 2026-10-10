package com.khrecast.recast;

import android.app.Activity;
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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
        view.releaseAll();
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
        if (pump != null) {
            pump.interrupt();
        }
        PyObject a = app;
        if (a != null && isFinishing()) {
            input.execute(() -> a.callAttr("stop"));
        }
        input.shutdown();
        super.onDestroy();
    }
}
