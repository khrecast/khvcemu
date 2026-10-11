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
import android.widget.SeekBar;
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

        col.addView(heading("Picture filter"));
        RadioGroup filters = new RadioGroup(this);
        String[] filterNames = {"Pixels (crisp)", "Smooth", "Sharp pixels", "Scale2x (rounded edges)"};
        for (int i = 0; i < filterNames.length; i++) {
            addSize(filters, filterNames[i], i, Settings.pictureFilter(this));
        }
        filters.setOnCheckedChangeListener((g, id) -> Settings.setPictureFilter(this, (Integer) g.findViewById(id).getTag()));
        col.addView(filters);
        col.addView(note("How the picture is enlarged. Crisp: every game pixel a sharp block. Smooth: softened. Sharp pixels: "
                + "crisp blocks with only the last fraction softened. Scale2x: rounds off the staircase edges without blurring."));

        col.addView(heading("Text size"));
        TextView textValue = text("The game's own text: " + Settings.textSize(this) + " pixels", 16, Color.WHITE);
        col.addView(textValue);
        SeekBar textBar = new SeekBar(this);
        textBar.setMax(8);                                     // 8 to 16
        textBar.setProgress(Settings.textSize(this) - 8);
        textBar.setContentDescription("Text size");
        textBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar b, int progress, boolean fromUser) {
                textValue.setText("The game's own text: " + (progress + 8) + " pixels");
                if (fromUser) {
                    Settings.setTextSize(OptionsActivity.this, progress + 8);
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar b) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar b) {
            }
        });
        col.addView(textBar);
        col.addView(note("11 is the usual size. Applies the next time the game starts."));

        col.addView(toggle("Sharp text", Settings.hiresText(this), Settings::setHiresText));
        col.addView(note("Draws the game's text at the screen's own resolution, with the phone's font, instead of enlarging the "
                + "game's small pixels. The picture stays as it is. Applies the next time the game starts."));

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

        col.addView(heading("Controls"));
        col.addView(toggle("Button names follow the game", Settings.liveSoftkeys(this), Settings::setLiveSoftkeys));
        col.addView(note("The two softkey buttons show the words the game puts above them (Select, Back, Continue...), and Action "
                + "shows what it will do (Open, Attack, Grab...) while the game's banner says so. Applies the next time the game starts."));
        col.addView(toggle("Flip phone look (upright only)", Settings.flipPhone(this), Settings::setFlipPhone));
        col.addView(note("Play it the way it was meant to be played: on a flip phone. The game sits in the screen of a 2005 clamshell "
                + "with softkeys, a navigation ring, Call and End keys and a 12-key keypad (2, 4, 6, 8 move, 5 selects, * is Magic, "
                + "0 is Status). The picture has a fixed size here. Turning the phone sideways uses the usual controls."));
        col.addView(flipColorRow());
        col.addView(toggle("Two-thumb controls (smartphone look)", Settings.twoThumb(this), Settings::setTwoThumb));
        col.addView(note("The game was made for a phone keypad, moved with two thumbs. Left thumb: forward and back, Magic and Status. "
                + "Right thumb: turn left and right, Action. No diagonals to aim for, so you cannot run in circles. Move and resize "
                + "each group from the game's menu; it keeps its own places, and \"Put the controls back\" returns to the built-in arrangement."));
        col.addView(toggle("Small bezel: a bigger picture (needs the flip phone look)", Settings.flipSmallBezel(this), Settings::setFlipSmallBezel));
        col.addView(note("Move and resize the touch controls from the game's menu (Back, then Move the controls): drag a control to "
                + "move it, pinch it with two fingers to make it bigger or smaller."));
        col.addView(Labels.pictureButton(this, R.drawable.menu_b_controls_reset, 28, 56, false,
                "Put the controls back to the default", v -> {
                    Settings.resetControls(this);
                    android.widget.Toast.makeText(this, "The controls are back in their usual places",
                            android.widget.Toast.LENGTH_SHORT).show();
                }));

        col.addView(heading("Sound"));
        col.addView(toggle("Mute the game", Settings.muted(this), Settings::setMuted));
        col.addView(Labels.pictureButton(this, R.drawable.menu_b_music_mix, 28, 56, false, "Music mix and sliders",
                v -> startActivity(new Intent(this, SoundActivity.class))));

        col.addView(heading("Online scores"));
        col.addView(toggle("Share high scores", Settings.shareScores(this), Settings::setShareScores));
        col.addView(note("Posts only the world, score, time, Munny, EXP and level to the project's leaderboard "
                + "(scores.khrecast.com). No name, account or device ID; your internet address is used only briefly, to limit how often you can post. Scores are always kept on this phone too. Applies "
                + "the next time the game starts."));
        final android.widget.FrameLayout[] test = new android.widget.FrameLayout[1];
        test[0] = Labels.pictureButton(this, R.drawable.menu_b_test_connection, 28, 56, false, "Test the connection",
                v -> testConnection(test[0]));
        col.addView(test[0]);

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

        android.widget.FrameLayout defaults = Labels.pictureButton(this, R.drawable.menu_b_restore, 28, 56, false,
                "Restore the default settings", v -> {
                    Settings.restoreDefaults(this);
                    build();                                   // show the defaults
                });
        ((LinearLayout.LayoutParams) defaults.getLayoutParams()).topMargin = dp(24);
        col.addView(defaults);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));
    }

    /** Asks the leaderboard for its top list (nothing is posted) and says whether it answered. */
    private void testConnection(android.widget.FrameLayout button) {
        Labels.enable(button, false);                              // greyed while the test runs
        new Thread(() -> {
            String result;
            try {
                if (!com.chaquo.python.Python.isStarted()) {
                    com.chaquo.python.Python.start(new com.chaquo.python.android.AndroidPlatform(getApplicationContext()));
                }
                result = com.chaquo.python.Python.getInstance().getModule("recast_app")
                        .callAttr("check_online", Settings.LEADERBOARD_URL).toString();
            } catch (Throwable t) {
                result = "The test could not run: " + t;
            }
            final String shown = result;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;                                            // the screen was closed while the test ran
                }
                Labels.enable(button, true);
                new android.app.AlertDialog.Builder(this).setTitle("Connection test").setMessage(shown)
                        .setPositiveButton("OK", null).show();
            });
        }, "recast-online-test").start();
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

    /** "Flip phone color" with a list of the body colors (it only shows when the flip phone look is on). */
    private View flipColorRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        TextView label = text("Flip phone color (needs the flip phone look)", 16, Color.WHITE);
        label.setPadding(0, dp(10), 0, 0);
        row.addView(label);
        android.widget.Spinner spinner = new android.widget.Spinner(this);
        spinner.setAdapter(new android.widget.ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, Settings.FLIP_COLORS));
        spinner.setSelection(Settings.flipColor(this));
        spinner.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(android.widget.AdapterView<?> parent, View v, int position, long id) {
                Settings.setFlipColor(OptionsActivity.this, position);
            }

            @Override
            public void onNothingSelected(android.widget.AdapterView<?> parent) {
            }
        });
        row.addView(spinner);
        return row;
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

    /** A heading in the menu font (the pictures are made by tools/make_tab_labels.py). */
    private View heading(String s) {
        int res;
        switch (s) {
            case "Picture size": res = R.drawable.menu_h_picture_size; break;
            case "Picture filter": res = R.drawable.menu_h_picture_filter; break;
            case "Text size": res = R.drawable.menu_h_text_size; break;
            case "Speed": res = R.drawable.menu_h_speed; break;
            case "Controls": res = R.drawable.menu_h_controls; break;
            case "Sound": res = R.drawable.menu_sound; break;     // (the screen title's picture, smaller)
            case "Online scores": res = R.drawable.menu_h_online; break;
            default: res = R.drawable.menu_h_autosave; break;
        }
        return Labels.heading(this, res, s);
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
