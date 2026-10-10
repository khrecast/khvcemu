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
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
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
    private boolean freshStart = true;                // false when Android restored this screen: one-time requests are not repeated
    private volatile int session = 0;               // which game (recast_app.start_game's number) this screen started
    private volatile PyObject app;                 // the recast_app module once the game has started
    private volatile boolean running = true;
    private volatile boolean resumed = false;      // the activity is in the foreground
    private volatile boolean inner = false;        // one of our own screens (Saves, Setup) was opened from the game
    private AlertDialog menu;
    private AlertDialog scoresDialog;
    private volatile boolean muted = false;
    private volatile boolean menuOpen = false;     // our menu is up: the game is held, like when the app is in the background
    private static final int REQ_SAVES = 1;
    private Thread pump;
    private Thread sound;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        freshStart = savedInstanceState == null;
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
        inputManager = (android.hardware.input.InputManager) getSystemService(INPUT_SERVICE);
        if (inputManager != null) {
            inputManager.registerInputDeviceListener(deviceListener, null);
        }
        view.setStatus("starting...");
        if (Build.VERSION.SDK_INT >= 33) {             // the system Back button and the back swipe open the game's menu
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    this::showMenu);
        }
        if (Settings.shareAsked(this)) {
            new Thread(this::startGame, "recast-start").start();
        } else {
            askAboutScores();                              // once; the game starts when the player has answered
        }
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
            String world = freshStart ? getIntent().getStringExtra(HomeActivity.EXTRA_START_WORLD) : null;
            getIntent().removeExtra(HomeActivity.EXTRA_START_WORLD);    // once, and before the call: nothing may reseed the save
            session = module.callAttr("start_game", getApplicationInfo().nativeLibraryDir, game.getAbsolutePath(),
                    data.getAbsolutePath(), world == null ? "" : world, Settings.speedOff(this),
                    Settings.frameLock(this), Settings.music(this),
                    Settings.shareScores(this) ? Settings.LEADERBOARD_URL : "", Settings.textSize(this)).toInt();
            app = module;
            String load = freshStart ? getIntent().getStringExtra(HomeActivity.EXTRA_LOAD) : null;
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

    private final boolean[] stick = new boolean[4];            // the stick's directions held: left, right, up, down
    private static final String[] STICK_KEYS = {"LEFT", "RIGHT", "UP", "DOWN"};

    /** Controller buttons: they press the phone keys (the game and its sound are held while a menu is up, as for touch). */
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        if (view != null && GamePad.fromPad(e) && !menuOpen) {
            String key = GamePad.keyFor(e.getKeyCode());
            if (key != null) {
                if (e.getRepeatCount() == 0) {
                    view.padKey(key, e.getAction() == KeyEvent.ACTION_DOWN, GamePad.FROM_BUTTONS);
                }
                return true;
            }
            if (GamePad.isMenu(e.getKeyCode())) {
                if (e.getAction() == KeyEvent.ACTION_DOWN && e.getRepeatCount() == 0 && app != null && !view.isEditing()) {
                    showMenu();
                }
                return true;
            }
        }
        return super.dispatchKeyEvent(e);
    }

    /** The left stick and the hat move like the D-pad. */
    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent e) {
        if (view != null && (e.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK
                && e.getAction() == MotionEvent.ACTION_MOVE) {
            float[] pos = GamePad.position(e);
            boolean[] now = menuOpen ? new boolean[4] : GamePad.directions(pos[0], pos[1]);
            for (int i = 0; i < 4; i++) {
                if (now[i] != stick[i]) {
                    stick[i] = now[i];
                    view.padKey(STICK_KEYS[i], now[i], GamePad.FROM_STICK);
                }
            }
            return true;
        }
        return super.dispatchGenericMotionEvent(e);
    }

    private android.hardware.input.InputManager inputManager;
    private final android.hardware.input.InputManager.InputDeviceListener deviceListener =
            new android.hardware.input.InputManager.InputDeviceListener() {
                @Override
                public void onInputDeviceAdded(int deviceId) {
                }

                @Override
                public void onInputDeviceChanged(int deviceId) {
                }

                @Override
                public void onInputDeviceRemoved(int deviceId) {         // a pad unplugged or switched off with a button held
                    runOnUiThread(MainActivity.this::releaseController);  // sends no key up: let go of it ourselves
                }
            };

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (!hasFocus) {
            releaseController();                                         // the notification shade, a dialog, split screen
        }
    }

    /** Lets go of the controller's keys and its stick (the game's menu or another screen takes over its events). */
    private void releaseController() {
        if (view != null) {
            view.releasePad();
        }
        java.util.Arrays.fill(stick, false);
    }

    /** The game's menu (the system Back button or swipe): the game is held while it is up. */
    private void showMenu() {
        if (app == null) {                             // still starting: Back leaves, as it did before the menu existed
            finish();
            return;
        }
        if (view.isEditing()) {                        // Back while moving the controls: done (they were saved as dropped)
            view.setEditing(false);
            applyLifecycle();                              // the game goes on
            Toast.makeText(this, "Controls saved", Toast.LENGTH_SHORT).show();
            return;
        }
        if (menuOpen) {
            return;
        }
        final String[] items = {"Resume", "Quick save (slot 1)", "Quick load (slot 1)", "Save to a slot...",
                "Load a saved game...", "Take a screenshot", "Move the controls", "Options...",
                "Quit and go to the Re:Cast menu"};
        menuOpen = true;
        releaseController();
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
                            takeScreenshot();
                            break;
                        case 6:
                            view.setEditing(true);
                            applyLifecycle();                  // hold the game while the controls are arranged
                            break;
                        case 7:
                            inner = true;
                            startActivity(new Intent(this, OptionsActivity.class));
                            break;
                        case 8:
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

    /** The first time the game starts: may high scores be shared with the project's leaderboard? Nothing is sent before the answer. */
    private void askAboutScores() {
        view.setStatus("waiting for your answer...");
        scoresDialog = new AlertDialog.Builder(this)
                .setTitle("Share your high scores?")
                .setMessage("When you finish a world, the game can post your score to the project's public leaderboard "
                        + "(scores.khrecast.com) so you can see how you rank.\n\nOnly the world, the score, how long the run "
                        + "took, and the Munny, EXP and level behind it are sent. No name, account or device ID; your internet address is used only briefly, to limit how often you can post. Scores are "
                        + "always kept on this phone too.\n\nYou can change this later in Options.")
                .setCancelable(false)
                .setPositiveButton("Share my scores", (d, w) -> answeredScores(true))
                .setNegativeButton("Keep scores on this phone", (d, w) -> answeredScores(false))
                .show();
    }

    private void answeredScores(boolean share) {
        Settings.setShareScores(this, share);                          // the answer is kept either way
        if (isDestroyed() || isFinishing()) {
            return;                                                    // the screen is gone: the next start asks nothing more
        }
        new Thread(this::startGame, "recast-start").start();
    }

    /** Saves the game's current picture to the gallery (Pictures/Re-Cast) and says where. */
    private void takeScreenshot() {
        android.graphics.Bitmap picture = view.snapshot();
        if (picture == null) {
            Toast.makeText(this, "Nothing to save yet", Toast.LENGTH_SHORT).show();
            return;
        }
        new Thread(() -> {
            try {
                String where = Screenshots.save(getApplicationContext(), picture);
                toast("Screenshot saved in " + where, Toast.LENGTH_SHORT);
            } catch (Exception e) {
                toast("Could not save the screenshot: " + (e.getMessage() != null ? e.getMessage() : e.toString()),
                        Toast.LENGTH_LONG);
            }
        }, "recast-screenshot").start();
    }

    /** A message from any thread (the application context, so it works even if the screen has gone). */
    private void toast(String text, int length) {
        android.content.Context app = getApplicationContext();
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> Toast.makeText(app, text, length).show());
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
        releaseController();
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
        runOnUiThread(() -> {
            view.setPictureScale(scale);
            view.setFilter(Settings.pictureFilter(MainActivity.this));
            view.reloadControlOffsets();                       // the controls may have been reset in Options
        });      // (this may run on the thread that starts the game)
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
        return resumed && !menuOpen && !(view != null && view.isEditing());   // the game is held while the controls are moved
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
        if (inputManager != null) {
            inputManager.unregisterInputDeviceListener(deviceListener);
        }
        if (menu != null && menu.isShowing()) {
            menu.dismiss();                            // no leaked window
        }
        if (scoresDialog != null && scoresDialog.isShowing()) {
            scoresDialog.dismiss();
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
