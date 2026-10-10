package com.khrecast.recast;

import java.util.Locale;

/**
 * The music synth's settings, as the Sound screen shows them: the same sliders, ranges and ready-made mixes as
 * khvcemu/music_settings.py (tests/test_android_assets.py fails if these tables and that module ever differ).
 * Every value is a multiplier on the sound the synth was tuned to, so 1.0 everywhere is the default sound.
 * A setting set is kept as the module's own text, "piano=0.8,bass_cut=1.5" (only what differs from 1.0).
 */
final class SoundSettings {
    /** {key, label, low, high}: the first VOLUME_COUNT are how loud each family is, the rest how the instruments sound. */
    static final String[][] SLIDERS = {
        {"master", "Music volume", "0.0", "2.0"},
        {"piano", "Piano", "0.0", "2.0"},
        {"strings", "Strings and choir", "0.0", "2.0"},
        {"brass", "Brass and horns", "0.0", "2.0"},
        {"harp", "Harp and guitar", "0.0", "2.0"},
        {"bells", "Bells and celesta", "0.0", "2.0"},
        {"winds", "Flutes and reeds", "0.0", "2.0"},
        {"pads", "Pads and organ", "0.0", "2.0"},
        {"bass", "Bass", "0.0", "2.0"},
        {"drums", "Drums and timpani", "0.0", "2.0"},
        {"hammer", "Piano hammer", "0.0", "3.0"},
        {"piano_tail", "Piano tail", "0.25", "3.0"},
        {"horn_length", "Horn note length", "0.25", "4.0"},
        {"bass_cut", "Bass cut", "0.0", "3.0"},
        {"high_soft", "High-note softening", "0.0", "2.5"},
    };
    /** How many of the sliders are about loudness (the rest are about character). */
    static final int VOLUME_COUNT = 10;

    /** {name, settings text}: the ready-made mixes, in the order they are listed. */
    static final String[][] PRESETS = {
        {"As tuned", ""},
        {"More bass", "bass=1.6,drums=1.3,bass_cut=0.3"},
        {"Bright and crisp", "hammer=1.6,high_soft=0.6,bells=1.2,piano_tail=0.8"},
        {"Big brass", "brass=1.4,drums=1.3,horn_length=0.7"},
        {"Soft and warm", "hammer=0.4,high_soft=1.6,brass=0.8,drums=0.7,pads=1.3,piano_tail=1.4"},
        {"Quiet background", "master=0.5"},
    };

    private SoundSettings() {
    }

    static float low(String[] slider) {
        return Float.parseFloat(slider[2]);
    }

    static float high(String[] slider) {
        return Float.parseFloat(slider[3]);
    }

    /** The value of one setting in a settings text (1.0 when it is not there or not a number). */
    static float value(String text, String key) {
        for (String part : text.split("[,;]")) {
            int eq = part.indexOf('=');
            if (eq > 0 && part.substring(0, eq).trim().equalsIgnoreCase(key)) {
                try {
                    return Float.parseFloat(part.substring(eq + 1).trim());
                } catch (NumberFormatException e) {
                    return 1f;
                }
            }
        }
        return 1f;
    }

    /** A settings text from slider values (in SLIDERS order): only the ones that are not 1.0. */
    static String text(float[] values) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < SLIDERS.length; i++) {
            if (Math.abs(values[i] - 1f) > 0.0005f) {
                sb.append(sb.length() > 0 ? "," : "").append(SLIDERS[i][0]).append('=')
                        .append(String.format(Locale.US, "%.3f", values[i]).replaceAll("0+$", "").replaceAll("\\.$", ""));
            }
        }
        return sb.toString();
    }

    /** The settings text in its one canonical form (only what differs from 1.0, in slider order). */
    static String normalize(String text) {
        float[] values = new float[SLIDERS.length];
        for (int i = 0; i < values.length; i++) {
            values[i] = value(text, SLIDERS[i][0]);
        }
        return text(values);
    }

    /** The name of the ready-made mix a settings text equals, or null when it is a custom mix. */
    static String presetNamed(String text) {
        String mine = normalize(text);
        for (String[] p : PRESETS) {
            float[] other = new float[SLIDERS.length];
            for (int i = 0; i < other.length; i++) {
                other[i] = value(p[1], SLIDERS[i][0]);
            }
            if (text(other).equals(mine)) {
                return p[0];
            }
        }
        return null;
    }
}
