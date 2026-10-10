package com.khrecast.recast;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.TextView;

import java.util.Locale;

/**
 * The Sound screen: a ready-made mix to start from, and a slider for each family of instruments and for how the piano and
 * horns sound (the same settings as the desktop launcher's Sound tab). Every change is saved at once and is heard the next
 * time the game starts (the game renders its music when it starts, and keeps what it has rendered for each setting).
 */
public class SoundActivity extends Activity {
    private static final int STEPS = 600;               // slider resolution

    private final SeekBar[] bars = new SeekBar[SoundSettings.SLIDERS.length];
    private final TextView[] values = new TextView[SoundSettings.SLIDERS.length];
    private Spinner mix;
    private boolean loading;                            // true while the screen sets the sliders itself

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int pad = dp(20);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Labels.picture(this, R.drawable.menu_sound, 32, Labels.maxWidth(this), false, "Sound"));

        col.addView(heading("Mix"));
        mix = new Spinner(this);
        String[] names = new String[SoundSettings.PRESETS.length + 1];
        for (int i = 0; i < SoundSettings.PRESETS.length; i++) {
            names[i] = SoundSettings.PRESETS[i][0];
        }
        names[names.length - 1] = "Custom";
        mix.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, names));
        col.addView(mix);
        col.addView(note("Pick a ready-made mix, or move the sliders for your own. Heard the next time the game starts. "
                + "The game's own sound effects are not changed. The first start after a change takes a few seconds longer "
                + "while the music is made."));

        for (int i = 0; i < SoundSettings.SLIDERS.length; i++) {
            if (i == 0) {
                col.addView(heading("How loud"));
            } else if (i == SoundSettings.VOLUME_COUNT) {
                col.addView(heading("How the instruments sound"));
            }
            col.addView(slider(i));
        }

        Button reset = new Button(this);
        reset.setText("Back to the sound the game was tuned to");
        Labels.theme(reset, false);
        reset.setOnClickListener(v -> setAll(""));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        lp.topMargin = dp(20);
        col.addView(reset, lp);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));

        setAll(Settings.music(this), false);
        mix.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (loading || position >= SoundSettings.PRESETS.length) {
                    return;
                }
                if (SoundSettings.PRESETS[position][0].equals(SoundSettings.presetNamed(Settings.music(SoundActivity.this)))) {
                    return;                                          // already this mix (the picker reports its starting choice)
                }
                setAll(SoundSettings.PRESETS[position][1]);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
    }

    private View slider(int i) {
        String[] s = SoundSettings.SLIDERS[i];
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, dp(8), 0, 0);
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        TextView label = text(s[1], 16, Color.WHITE);
        label.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        head.addView(label);
        values[i] = text("", 14, 0xFF8EA4BF);
        head.addView(values[i]);
        row.addView(head);
        SeekBar bar = new SeekBar(this);
        bar.setMax(STEPS);
        bar.setContentDescription(s[1]);
        bars[i] = bar;
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar b, int progress, boolean fromUser) {
                values[i].setText(String.format(Locale.US, "%.2f", valueOf(i)));
                if (fromUser) {
                    changed();
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar b) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar b) {
            }
        });
        row.addView(bar);
        return row;
    }

    private float valueOf(int i) {
        String[] s = SoundSettings.SLIDERS[i];
        float low = SoundSettings.low(s), high = SoundSettings.high(s);
        return low + (high - low) * bars[i].getProgress() / STEPS;
    }

    private void setAll(String text) {
        setAll(text, true);
    }

    /** Puts a whole settings text on the sliders (and saves it, when asked). */
    private void setAll(String text, boolean save) {
        loading = true;
        for (int i = 0; i < bars.length; i++) {
            String[] s = SoundSettings.SLIDERS[i];
            float low = SoundSettings.low(s), high = SoundSettings.high(s);
            float v = Math.min(high, Math.max(low, SoundSettings.value(text, s[0])));
            bars[i].setProgress(Math.round((v - low) / (high - low) * STEPS));
            values[i].setText(String.format(Locale.US, "%.2f", v));
        }
        loading = false;
        if (save) {
            Settings.setMusic(this, normalized(text));                // exactly what was chosen, not re-read from the sliders
        }
        showMixName();
    }

    /** The text for a whole set of values: each one clamped to its slider's range (as the module does). */
    private static String normalized(String text) {
        float[] v = new float[SoundSettings.SLIDERS.length];
        for (int i = 0; i < v.length; i++) {
            String[] s = SoundSettings.SLIDERS[i];
            v[i] = Math.min(SoundSettings.high(s), Math.max(SoundSettings.low(s), SoundSettings.value(text, s[0])));
        }
        return SoundSettings.text(v);
    }

    /** A slider moved: save the settings and show which mix they make. */
    private void changed() {
        if (loading) {
            return;
        }
        float[] now = new float[bars.length];
        for (int i = 0; i < now.length; i++) {
            now[i] = valueOf(i);
            String[] s = SoundSettings.SLIDERS[i];
            if (Math.abs(now[i] - 1f) < (SoundSettings.high(s) - SoundSettings.low(s)) / STEPS) {
                now[i] = 1f;                                          // the slider cannot land exactly on 1.0: close counts
            }
        }
        Settings.setMusic(this, SoundSettings.text(now));
        showMixName();
    }

    private void showMixName() {
        String name = SoundSettings.presetNamed(Settings.music(this));
        int position = SoundSettings.PRESETS.length;                 // "Custom"
        for (int i = 0; i < SoundSettings.PRESETS.length; i++) {
            if (SoundSettings.PRESETS[i][0].equals(name)) {
                position = i;
            }
        }
        if (mix.getSelectedItemPosition() != position) {
            mix.setSelection(position);                              // (the picker's callback ignores a mix that is already saved)
        }
    }

    private TextView heading(String s) {
        TextView t = text(s, 18, 0xFF5B9DFF);
        t.setPadding(0, dp(22), 0, dp(6));
        return t;
    }

    private TextView note(String s) {
        TextView t = text(s, 13, 0xFF8EA4BF);
        t.setPadding(0, dp(4), 0, 0);
        return t;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
