package com.khrecast.recast;

import android.app.Activity;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
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

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

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
    private Button deleteMix;
    private java.util.List<String> mixNames = new java.util.ArrayList<>();   // ready-made mixes, saved mixes, then "Custom"
    private boolean loading;                            // true while the screen sets the sliders itself
    private Spinner tune;
    private Button playButton;
    private TextView tuneStatus;
    private AudioTrack track;                           // the tune being played (looping), or null
    private boolean wantPlaying;                        // the player pressed Play and has not pressed Stop
    private int renderToken;                            // a newer request makes an older render's result obsolete
    private boolean rendering;                          // one tune is made at a time (the interpreter is shared with the game)
    private boolean renderAgain;                        // asked again while one was being made: make it again when it ends
    private static final Object PYTHON_START = new Object();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable restart = this::startTune;   // after the sliders move: make the tune again

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int pad = dp(20);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Labels.picture(this, R.drawable.menu_sound, 32, Labels.maxWidth(this), false, "Sound"));

        col.addView(heading("Try the music"));
        tune = new Spinner(this);
        String[] tuneNames = new String[SoundSettings.TUNES.length];
        for (int i = 0; i < tuneNames.length; i++) {
            tuneNames[i] = SoundSettings.TUNES[i][1];
        }
        tune.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, tuneNames));
        col.addView(tune);
        playButton = new Button(this);
        playButton.setText("Play");
        Labels.theme(playButton, true);
        playButton.setOnClickListener(v -> {
            if (wantPlaying) {
                stopTune();
            } else {
                wantPlaying = true;
                startTune();
            }
        });
        LinearLayout.LayoutParams playLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        playLp.topMargin = dp(6);
        col.addView(playButton, playLp);
        tuneStatus = note("Plays the tune with the sliders below, over and over. Move a slider and it is made again a moment "
                + "later, so you can tune by ear. Pick another tune while it plays to change over.");
        col.addView(tuneStatus);
        tune.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (wantPlaying) {
                    startTune();
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });

        col.addView(heading("Mix"));
        mix = new Spinner(this);
        col.addView(mix);
        LinearLayout mixButtons = new LinearLayout(this);
        mixButtons.setOrientation(LinearLayout.HORIZONTAL);
        Button saveMix = new Button(this);
        saveMix.setText("Save this mix...");
        Labels.theme(saveMix, false);
        saveMix.setOnClickListener(v -> askMixName());
        deleteMix = new Button(this);
        deleteMix.setText("Delete this mix");
        Labels.theme(deleteMix, false);
        deleteMix.setOnClickListener(v -> confirmDeleteMix());
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, dp(48), 1f);
        half.rightMargin = dp(4);
        LinearLayout.LayoutParams halfRight = new LinearLayout.LayoutParams(0, dp(48), 1f);
        halfRight.leftMargin = dp(4);
        mixButtons.addView(saveMix, half);
        mixButtons.addView(deleteMix, halfRight);
        LinearLayout.LayoutParams mixRow = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        mixRow.topMargin = dp(6);
        col.addView(mixButtons, mixRow);
        col.addView(note("Pick a ready-made mix, or move the sliders for your own. Press Play above to hear it now; the game uses it the next time it starts. "
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

        rebuildMixList();
        setAll(Settings.music(this), false);
        mix.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String chosen = textOfMix(position);
                updateDeleteButton();
                if (loading || chosen == null) {
                    return;                                          // "Custom" is not a mix to apply
                }
                if (SoundSettings.normalize(chosen).equals(SoundSettings.normalize(Settings.music(SoundActivity.this)))) {
                    return;                                          // already this mix (the picker reports its starting choice)
                }
                setAll(chosen);
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
            scheduleRestart();
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
        scheduleRestart();
    }

    /** While a tune is playing, a changed setting makes it again after the player pauses (a slider sends many changes). */
    private void scheduleRestart() {
        if (wantPlaying) {
            ui.removeCallbacks(restart);
            ui.postDelayed(restart, 700);
        }
    }

    /** Makes the chosen tune with the saved music settings (a few seconds, off the screen's thread) and plays it in a loop. */
    private void startTune() {
        if (!wantPlaying) {
            return;
        }
        ui.removeCallbacks(restart);
        silence();
        playButton.setText("Stop");
        tuneStatus.setText("Making the music...");
        if (rendering) {
            renderAgain = true;                                     // not two at once: this one starts when the first ends
            return;
        }
        rendering = true;
        final int token = ++renderToken;
        final String name = SoundSettings.TUNES[Math.max(0, tune.getSelectedItemPosition())][0];
        final String settings = Settings.music(this);
        new Thread(() -> {
            try {
                synchronized (PYTHON_START) {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(getApplicationContext()));
                    }
                }
                PyObject app = Python.getInstance().getModule("recast_app");
                byte[] pcm = app.callAttr("render_tune", GameInstaller.gameDir(this).getAbsolutePath(), name, settings)
                        .toJava(byte[].class);
                runOnUiThread(() -> {
                    rendering = false;
                    if (renderAgain) {
                        renderAgain = false;
                        startTune();                                 // the settings changed meanwhile: this one is out of date
                    } else if (token == renderToken && wantPlaying && !isDestroyed()) {
                        playLoop(pcm);
                    }
                });
            } catch (Throwable e) {
                runOnUiThread(() -> {
                    rendering = false;
                    renderAgain = false;
                    if (token == renderToken && !isDestroyed()) {
                        wantPlaying = false;
                        playButton.setText("Play");
                        tuneStatus.setText("Could not make that tune: " + (e.getMessage() == null ? e.toString() : e.getMessage()));
                    }
                });
            }
        }, "tune-render").start();
    }

    private void playLoop(byte[] pcm) {
        silence();
        AudioTrack t = null;
        try {
            t = new AudioTrack.Builder()
                    .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(22050).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                    .setBufferSizeInBytes(Math.max(pcm.length, 4096))
                    .setTransferMode(AudioTrack.MODE_STATIC)
                    .build();
            if (t.write(pcm, 0, pcm.length) != pcm.length) {
                throw new IllegalStateException("the sound did not fit in the player");
            }
            t.setLoopPoints(0, pcm.length / 2, -1);
            t.play();
            track = t;
            tuneStatus.setText("Playing. Move the sliders to change it.");
        } catch (RuntimeException e) {
            if (t != null) {
                t.release();
            }
            wantPlaying = false;
            playButton.setText("Play");
            tuneStatus.setText("Could not play it: " + (e.getMessage() == null ? e.toString() : e.getMessage()));
        }
    }

    private void silence() {
        AudioTrack t = track;
        track = null;
        if (t != null) {
            try {
                t.stop();
            } catch (IllegalStateException ignored) {
            }
            t.release();
        }
    }

    private void stopTune() {
        wantPlaying = false;
        renderAgain = false;
        renderToken++;
        ui.removeCallbacks(restart);
        silence();
        playButton.setText("Play");
        tuneStatus.setText("Stopped.");
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (wantPlaying) {
            stopTune();                                             // no music behind another screen
        }
    }

    @Override
    protected void onDestroy() {
        wantPlaying = false;
        renderToken++;
        ui.removeCallbacks(restart);
        silence();
        super.onDestroy();
    }

    /** The settings text of the mix at a position of the Mix list, or null for "Custom". */
    private String textOfMix(int position) {
        if (position < 0 || position >= mixNames.size() - 1) {
            return null;
        }
        if (position < SoundSettings.PRESETS.length) {
            return SoundSettings.PRESETS[position][1];
        }
        return Settings.mixes(this).get(mixNames.get(position));
    }

    /** The Mix list: the ready-made mixes, the player's saved ones, then "Custom". */
    private void rebuildMixList() {
        mixNames = new java.util.ArrayList<>();
        for (String[] p : SoundSettings.PRESETS) {
            mixNames.add(p[0]);
        }
        for (java.util.Map.Entry<String, String> e : Settings.mixes(this).entrySet()) {
            boolean twin = false;                                    // a damaged entry that equals a ready-made mix cannot be told apart
            for (String[] p : SoundSettings.PRESETS) {
                twin |= SoundSettings.normalize(p[1]).equals(SoundSettings.normalize(e.getValue()));
            }
            if (!twin) {
                mixNames.add(e.getKey());
            }
        }
        mixNames.add("Custom");
        // (the picker reports its starting choice after the next layout; the callback ignores a mix that is already in force)
        mix.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, mixNames));
    }

    /** Which entry of the Mix list the current sliders are: a ready-made mix, a saved one, or "Custom". */
    private void showMixName() {
        String current = SoundSettings.normalize(Settings.music(this));
        int position = mixNames.size() - 1;                          // "Custom"
        for (int i = 0; i < mixNames.size() - 1; i++) {
            String text = textOfMix(i);
            if (text != null && SoundSettings.normalize(text).equals(current)) {
                position = i;
                break;
            }
        }
        if (mix.getSelectedItemPosition() != position) {
            mix.setSelection(position);                              // (the picker's callback ignores a mix that is already saved)
        }
        updateDeleteButton(position);
    }

    private void updateDeleteButton() {
        updateDeleteButton(mix.getSelectedItemPosition());
    }

    /** "Delete this mix" is for the player's own saved mixes only. */
    private void updateDeleteButton(int position) {
        boolean own = position >= SoundSettings.PRESETS.length && position < mixNames.size() - 1;
        deleteMix.setEnabled(own);
    }

    private void askMixName() {
        android.widget.EditText input = new android.widget.EditText(this);
        input.setHint("Name of this mix");
        input.setSingleLine(true);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(40)});
        new android.app.AlertDialog.Builder(this).setTitle("Save this mix").setView(input)
                .setPositiveButton("Save", (d, w) -> saveMixAs(Settings.cleanMixName(input.getText().toString())))
                .setNegativeButton("Cancel", null).show();
    }

    private void saveMixAs(String name) {
        if (name.isEmpty()) {
            return;
        }
        if (name.equalsIgnoreCase("Custom")) {
            android.widget.Toast.makeText(this, "Custom is the name of unsaved sliders: pick another",
                    android.widget.Toast.LENGTH_LONG).show();
            return;
        }
        for (String[] p : SoundSettings.PRESETS) {
            if (p[0].equalsIgnoreCase(name)) {
                android.widget.Toast.makeText(this, "That name belongs to a ready-made mix: pick another",
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        String current = SoundSettings.normalize(Settings.music(this));
        for (String[] p : SoundSettings.PRESETS) {                  // two mixes with the same settings could not be told apart
            if (SoundSettings.normalize(p[1]).equals(current)) {
                android.widget.Toast.makeText(this, "These settings are the ready-made mix " + p[0] + ": change a slider first",
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        for (java.util.Map.Entry<String, String> e : Settings.mixes(this).entrySet()) {
            if (!e.getKey().equalsIgnoreCase(name) && SoundSettings.normalize(e.getValue()).equals(current)) {
                android.widget.Toast.makeText(this, "These settings are already saved as " + e.getKey(),
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        boolean exists = false;
        for (String saved : Settings.mixes(this).keySet()) {
            exists |= saved.equalsIgnoreCase(name);
        }
        if (exists) {
            new android.app.AlertDialog.Builder(this).setTitle("Replace " + name + "?")
                    .setMessage("A mix with this name is already saved.")
                    .setPositiveButton("Replace", (d, w) -> writeMix(name))
                    .setNegativeButton("Cancel", null).show();
        } else {
            writeMix(name);
        }
    }

    private void writeMix(String name) {
        Settings.saveMix(this, name, Settings.music(this));
        rebuildMixList();
        showMixName();
        android.widget.Toast.makeText(this, "Saved as " + name, android.widget.Toast.LENGTH_SHORT).show();
    }

    private void confirmDeleteMix() {
        int position = mix.getSelectedItemPosition();
        if (position < SoundSettings.PRESETS.length || position >= mixNames.size() - 1) {
            return;
        }
        String name = mixNames.get(position);
        new android.app.AlertDialog.Builder(this).setTitle("Delete " + name + "?")
                .setMessage("The sliders stay as they are; only the saved name goes.")
                .setPositiveButton("Delete", (d, w) -> {
                    Settings.deleteMix(this, name);
                    rebuildMixList();
                    showMixName();
                })
                .setNegativeButton("Cancel", null).show();
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
