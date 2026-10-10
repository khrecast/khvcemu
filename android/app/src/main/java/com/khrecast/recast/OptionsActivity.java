package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;

/** Options: the picture size, mute and the autosave switches. Every change is saved at once; the game picks it up when it resumes. */
public class OptionsActivity extends Activity {
    private static final int[] MINUTES = {0, 2, 5, 10, 15};

    private LinearLayout col;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        build();
    }

    private void build() {
        int pad = dp(20);
        col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Labels.picture(this, R.drawable.menu_options, 32, Labels.maxWidth(this), false, "Options"));

        col.addView(heading("Picture size"));
        RadioGroup sizes = new RadioGroup(this);
        int current = Settings.pictureScale(this);
        android.util.DisplayMetrics screen = getResources().getDisplayMetrics();
        int most = Math.max(1, Math.min(screen.widthPixels, screen.heightPixels) / GameView.W);   // the narrow side, so both orientations
        addSize(sizes, "Fit the screen (crisp pixels, any size)", Settings.FIT, current);
        addSize(sizes, "Sharp: the largest whole-number size that fits", Settings.LARGEST, current);
        for (int n = most; n >= 1; n--) {
            addSize(sizes, n == 1 ? "1x: the original size, " + GameView.W + " x " + GameView.H + " pixels"
                    : n + "x: " + (GameView.W * n) + " x " + (GameView.H * n) + " pixels", n, current);
        }
        sizes.setOnCheckedChangeListener((g, id) -> Settings.setPictureScale(this, (Integer) g.findViewById(id).getTag()));
        col.addView(sizes);
        col.addView(note("Whole-number sizes keep every pixel the same size. Sizes too big for the screen use the largest that fits."));

        col.addView(heading("Speed"));
        col.addView(toggle("Steady frame rate", Settings.frameLock(this), Settings::setFrameLock));
        col.addView(note("Lets the game run at its own 25 frames a second whenever the phone keeps up. The game's speed and "
                + "your saves do not change."));
        col.addView(toggle("Faster blended fill", Settings.speedSpan(this), Settings::setSpeedSpan));
        col.addView(note("Draws water, glows and fades with a tighter loop. The picture is identical."));
        col.addView(toggle("Matrix cache", Settings.speedMatinv(this), Settings::setSpeedMatinv));
        col.addView(note("Remembers 3D matrix answers the engine asks for hundreds of times a frame. The picture is identical. "
                + "Save states made with it carry about 580 KB more."));
        col.addView(note("All three are on by default. Changes take effect the next time the game starts. Turn one off only to "
                + "compare speed or to see whether it is behind a problem."));

        col.addView(heading("Sound"));
        col.addView(toggle("Mute the game", Settings.muted(this), Settings::setMuted));
        Button sound = new Button(this);
        sound.setText("Music mix and sliders...");
        Labels.theme(sound, false);
        sound.setOnClickListener(v -> startActivity(new Intent(this, SoundActivity.class)));
        LinearLayout.LayoutParams soundParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        soundParams.topMargin = dp(8);
        col.addView(sound, soundParams);

        col.addView(heading("Autosave"));
        col.addView(toggle("Autosave", Settings.autosave(this), Settings::setAutosave));
        col.addView(toggle("At loading screens", Settings.autosaveOnLoading(this), Settings::setAutosaveOnLoading));
        col.addView(toggle("When leaving the game", Settings.autosaveOnQuit(this), Settings::setAutosaveOnQuit));
        col.addView(text("Every few minutes of play", 16, Color.WHITE));
        Spinner every = new Spinner(this);
        String[] labels = new String[MINUTES.length];
        int selected = 2;                                      // 5 minutes, if the saved value is not in the list
        for (int i = 0; i < MINUTES.length; i++) {
            labels[i] = MINUTES[i] == 0 ? "Never" : MINUTES[i] + " minutes";
            if (MINUTES[i] == Settings.autosaveMinutes(this)) {
                selected = i;
            }
        }
        every.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
        every.setSelection(selected);
        every.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                Settings.setAutosaveMinutes(OptionsActivity.this, MINUTES[position]);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        col.addView(every);
        col.addView(note("Autosaves only happen when you have played since the last save or load."));

        Button defaults = new Button(this);
        defaults.setText("Restore the default settings");
        Labels.theme(defaults, false);
        defaults.setOnClickListener(v -> {
            Settings.restoreDefaults(this);
            build();                                           // show the defaults
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        lp.topMargin = dp(24);
        col.addView(defaults, lp);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));
    }

    private void addSize(RadioGroup group, String label, int value, int current) {
        RadioButton b = new RadioButton(this);
        b.setText(label);
        b.setTextColor(Color.WHITE);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        b.setTag(value);
        b.setId(View.generateViewId());
        group.addView(b);
        b.setChecked(value == current);
    }

    private interface Setter {
        void set(android.content.Context c, boolean v);
    }

    private Switch toggle(String label, boolean on, Setter setter) {
        Switch s = new Switch(this);
        s.setText(label);
        s.setTextColor(Color.WHITE);
        s.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        s.setChecked(on);
        s.setPadding(0, dp(8), 0, dp(8));
        s.setOnCheckedChangeListener((CompoundButton b, boolean checked) -> setter.set(this, checked));
        return s;
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
