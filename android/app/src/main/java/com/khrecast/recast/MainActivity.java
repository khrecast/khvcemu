package com.khrecast.recast;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.widget.TextView;

/** Spike 1, step 1: can this app load Unicorn and run ARM code at target SDK 36? Shows the result on screen and in logcat. */
public class MainActivity extends Activity {
    static {
        System.loadLibrary("unicorn_probe");
    }

    private static native String runUnicornProbe();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String result;
        try {
            result = runUnicornProbe();
        } catch (Throwable t) {
            result = "FAILED: " + t;
        }
        Log.i("recast", result);
        TextView view = new TextView(this);
        view.setText(result);
        view.setTextSize(18f);
        view.setTextColor(Color.WHITE);
        view.setBackgroundColor(Color.BLACK);
        view.setGravity(Gravity.CENTER);
        view.setPadding(32, 32, 32, 32);
        setContentView(view);
    }
}
