package com.khrecast.recast;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.widget.Toast;
import android.view.WindowManager;
import android.window.OnBackInvokedDispatcher;

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
    private volatile int session = 0;               // which game (recast_app.start_game's number) this screen started
    private volatile PyObject app;                 // the recast_app module once the game has started
    private volatile boolean running = true;
    private volatile boolean resumed = false;      // the activity is in the foreground
    private volatile boolean inner = false;        // one of our own screens (Saves, Setup) was opened from the game
    private AlertDialog menu;
    private volatile boolean muted = false;
    private volatile boolean menuOpen = false;     // our menu is up: the game is held, like when the app is in the background
    private static final int REQ_SAVES = 1;
    private Thread pump;
    private Thread sound;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (!GameInstaller.isInstalled(this) && !new File(new File(getFilesDir(), "game"), "mod").isDirectory()) {
            if (isTaskRoot()) {                                        // no game files yet: start from the front (notice, then Home)
                startActivity(new Intent(this, DisclaimerActivity.class));
            }
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
        if (Build.VERSION.SDK_INT >= 33) {             // the system Back button and the back swipe open the game's menu
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    this::showMenu);
        }
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
            session = module.callAttr("start_game", getApplicationInfo().nativeLibraryDir, game.getAbsolutePath(),
                    data.getAbsolutePath()).toInt();
            app = module;
            String load = getIntent().getStringExtra(HomeActivity.EXTRA_LOAD);
            if (load != null) {
                getIntent().removeExtra(HomeActivity.EXTRA_LOAD);   // once: a recreated activity must not load it again
                requestState("load", load);                // Continue or a saved game was chosen on the home screen
            }
            applySettings();
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

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {                      // phones before Android 13 (the newer ones use the callback above)
        showMenu();
    }

    /** The game's menu (the system Back button or swipe): the game is held while it is up. */
    private void showMenu() {
        if (app == null) {                             // still starting: Back leaves, as it did before the menu existed
            finish();
            return;
        }
        if (menuOpen) {
            return;
        }
        final String[] items = {"Resume", "Quick save (slot 1)", "Quick load (slot 1)", "Save to a slot...",
                "Load a saved game...", "Options...", "Quit and go to the Re:Cast menu"};
        menuOpen = true;
        applyLifecycle();
        menu = new AlertDialog.Builder(this)
                .setTitle("Re:Cast")
                .setItems(items, (d, which) -> {
                    switch (which) {
                        case 1:
                            requestState("save", "1");
                            break;
                        case 2:
                            requestState("load", "1");
                            break;
                        case 3:
                        case 4:
                            inner = true;
                            startActivityForResult(new Intent(this, SavesActivity.class)
                                    .putExtra(SavesActivity.EXTRA_MODE, which == 3 ? "save" : "load"), REQ_SAVES);
                            break;
                        case 5:
                            inner = true;
                            startActivity(new Intent(this, OptionsActivity.class));
                            break;
                        case 6:
                            stopGame();                // now, not only when the system gets round to destroying the screen
                            finish();                  // the core autosaves on the way out (if anything was played)
                            break;
                        default:
                            break;
                    }
                })
                .setOnDismissListener(d -> {
                    menuOpen = false;
                    applyLifecycle();
                })
                .show();
    }

    private void stopGame() {
        PyObject a = app;
        if (a != null) {
            try {
                a.callAttr("stop", session);           // only the game this screen started
            } catch (Throwable t) {
                Log.w(TAG, "stop failed: " + t);
            }
        }
    }

    private void requestState(String op, String slot) {
        input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    a.callAttr("request_state", op, slot);
                } catch (Throwable t) {
                    Log.w(TAG, "state request failed: " + t);
                }
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SAVES && resultCode == RESULT_OK && data != null) {
            requestState(data.getStringExtra(SavesActivity.EXTRA_MODE), data.getStringExtra(SavesActivity.EXTRA_SLOT));
        }
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
                if (!active()) {
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
                if (muted) {
                    java.util.Arrays.fill(block, (byte) 0);    // the core keeps running; only what we hear is silenced
                }
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
        long last = -1, lastStatus = 0, lastMessage = 0;
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
                Thread.sleep(active() ? 8 : 250);
                if (now - lastMessage > 250) {                 // what a save or load said (once)
                    lastMessage = now;
                    String said = a.callAttr("take_message").toString();
                    if (!said.isEmpty()) {
                        runOnUiThread(() -> Toast.makeText(this, said, Toast.LENGTH_SHORT).show());
                    }
                }
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

    /** Picks up the Options screen's choices: the picture size and mute here, the autosave switches in the core. */
    private void applySettings() {
        if (view == null) {
            return;
        }
        final int scale = Settings.pictureScale(this);
        runOnUiThread(() -> view.setPictureScale(scale));      // (this may run on the thread that starts the game)
        muted = Settings.muted(this);
        final boolean autosave = Settings.autosave(this), onLoading = Settings.autosaveOnLoading(this),
                onQuit = Settings.autosaveOnQuit(this);
        final int minutes = Settings.autosaveMinutes(this);
        input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    a.callAttr("configure", autosave, minutes, onLoading, onQuit);
                } catch (Throwable t) {
                    Log.w(TAG, "configure failed: " + t);
                }
            }
        });
    }

    private boolean active() {
        return resumed && !menuOpen;
    }

    /** Tells the core whether the app is in the foreground. Queued on the input thread, and the flag is read when the
     *  task runs, so the last state always wins whatever the order of onPause, onResume and the game starting. */
    private void applyLifecycle() {
        input.execute(() -> {
            PyObject a = app;
            if (a != null) {
                try {
                    if (active()) {
                        a.callAttr("resume");
                    } else {
                        a.callAttr("pause", resumed || inner);   // only our own screens hold the game: no autosave for that
                    }
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
        inner = false;
        applySettings();
        applyLifecycle();
    }

    @Override
    protected void onDestroy() {
        running = false;
        if (menu != null && menu.isShowing()) {
            menu.dismiss();                            // no leaked window
        }
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
            try {
                a.callAttr("stop", session);           // at once (a flag), so a game started right after cannot reuse this one
            } catch (Throwable t) {
                Log.w(TAG, "stop failed: " + t);
            }
        }
        input.shutdown();
        super.onDestroy();
    }
}
