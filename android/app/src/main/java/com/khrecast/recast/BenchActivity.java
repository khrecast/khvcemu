package com.khrecast.recast;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.ScrollView;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;

/**
 * Spike 1: (1) can this app load Unicorn and run ARM code at target SDK 36 (native probe), and
 * (2) does the unmodified Python core boot to the title screen inside Chaquopy (bench_headless.py boot)?
 * The results are shown on screen and logged with the tag "recast".
 */
public class BenchActivity extends Activity {
    static {
        System.loadLibrary("unicorn_probe");
    }

    private static native String runUnicornProbe();

    private TextView view;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        view = new TextView(this);
        view.setTextSize(11f);
        view.setTypeface(Typeface.MONOSPACE);
        view.setTextColor(Color.WHITE);
        view.setBackgroundColor(Color.BLACK);
        view.setGravity(Gravity.TOP);
        view.setPadding(24, 48, 24, 24);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(view);
        setContentView(scroll);

        show("starting...");
        new Thread(this::work, "recast-spike").start();
    }

    private void show(String text) {
        Log.i("recast", text);
        runOnUiThread(() -> view.setText(text));
    }

    private void work() {
        StringBuilder all = new StringBuilder();
        try {
            all.append("[native probe]\n").append(runUnicornProbe()).append("\n\n");
        } catch (Throwable t) {
            all.append("[native probe] FAILED: ").append(t).append("\n\n");
        }
        show(all + "[python] starting Chaquopy...");

        File game = new File(getFilesDir(), "game");
        String libDir = getApplicationInfo().nativeLibraryDir;
        if (!new File(game, "mod").isDirectory()) {
            all.append("[python] the game files are not in ").append(game).append("\n")
                    .append("copy mif/, mod/ and savegame(island).dat there (android/NOTES.md, Chunk 4).");
            show(all.toString());
            return;
        }
        try {
            long t0 = System.nanoTime();
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python py = Python.getInstance();
            PyObject app = py.getModule("recast_app");
            all.append(String.format("[python] started in %.1f s\n", (System.nanoTime() - t0) / 1e9));
            show(all + "[python] booting the core to the title (about 10 s)...");
            for (String mode : new String[] {"boot", "world", "audio"}) {
                long t1 = System.nanoTime();
                String out = app.callAttr("run_benchmark", mode, libDir, game.getAbsolutePath()).toString();
                all.append(String.format("\n[bench %s] (%.1f s)\n", mode, (System.nanoTime() - t1) / 1e9)).append(out);
                show(all + "\n...");
            }
        } catch (Throwable t) {
            all.append("\n[python] FAILED: ").append(t);
        }
        show(all.toString());
    }
}
