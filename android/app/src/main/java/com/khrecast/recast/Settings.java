package com.khrecast.recast;

import android.content.Context;
import android.content.SharedPreferences;

/** The app's few settings (SharedPreferences "recast"). The Options screen writes them; the game reads them when it resumes. */
final class Settings {
    /** Picture size: FIT fills the width (at most 60% of the height); LARGEST is the largest whole-number scale that
     *  fits (sharp pixels); 1, 2, 3... is exactly that many screen pixels per game pixel (1 is the original size). */
    static final int FIT = 0, LARGEST = -1;

    private Settings() {
    }

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("recast", Context.MODE_PRIVATE);
    }

    static int pictureScale(Context c) {
        return prefs(c).getInt("scale", FIT);
    }

    static void setPictureScale(Context c, int v) {
        prefs(c).edit().putInt("scale", v).apply();
    }

    static boolean muted(Context c) {
        return prefs(c).getBoolean("mute", false);
    }

    static void setMuted(Context c, boolean v) {
        prefs(c).edit().putBoolean("mute", v).apply();
    }

    static boolean autosave(Context c) {
        return prefs(c).getBoolean("autosave", true);
    }

    static void setAutosave(Context c, boolean v) {
        prefs(c).edit().putBoolean("autosave", v).apply();
    }

    /** Minutes of play between timed autosaves; 0 means none. */
    static int autosaveMinutes(Context c) {
        return prefs(c).getInt("autosave_minutes", 5);
    }

    static void setAutosaveMinutes(Context c, int v) {
        prefs(c).edit().putInt("autosave_minutes", v).apply();
    }

    static boolean autosaveOnLoading(Context c) {
        return prefs(c).getBoolean("autosave_loading", true);
    }

    static void setAutosaveOnLoading(Context c, boolean v) {
        prefs(c).edit().putBoolean("autosave_loading", v).apply();
    }

    static boolean autosaveOnQuit(Context c) {
        return prefs(c).getBoolean("autosave_quit", true);
    }

    static void setAutosaveOnQuit(Context c, boolean v) {
        prefs(c).edit().putBoolean("autosave_quit", v).apply();
    }

    /** The 3D engine's speed enhancements and the steady frame rate: all on unless switched off (taking effect when the game
     *  next starts). Names are the core's: "span" and "matinv" (khvcemu/swerve_patch.py). */
    static boolean speedSpan(Context c) {
        return prefs(c).getBoolean("speed_span", true);
    }

    static void setSpeedSpan(Context c, boolean v) {
        prefs(c).edit().putBoolean("speed_span", v).apply();
    }

    static boolean speedMatinv(Context c) {
        return prefs(c).getBoolean("speed_matinv", true);
    }

    static void setSpeedMatinv(Context c, boolean v) {
        prefs(c).edit().putBoolean("speed_matinv", v).apply();
    }

    static boolean frameLock(Context c) {
        return prefs(c).getBoolean("frame_lock", true);
    }

    static void setFrameLock(Context c, boolean v) {
        prefs(c).edit().putBoolean("frame_lock", v).apply();
    }

    /** The patches switched off, as the comma list the core takes. */
    static String speedOff(Context c) {
        StringBuilder off = new StringBuilder();
        if (!speedSpan(c)) {
            off.append("span");
        }
        if (!speedMatinv(c)) {
            off.append(off.length() > 0 ? "," : "").append("matinv");
        }
        return off.toString();
    }

    /** The music synth settings as the module's text, "piano=0.8,bass_cut=1.5" ("" = as tuned). See SoundSettings. */
    static String music(Context c) {
        return prefs(c).getString("music", "");
    }

    static void setMusic(Context c, String text) {
        prefs(c).edit().putString("music", text).apply();
    }

    /** The project's leaderboard (the same address as LEADERBOARD_URL in khvcemu/launcher.py; a test keeps them equal). */
    static final String LEADERBOARD_URL = "https://scores.khrecast.com";

    /** Whether the player has been asked about sharing high scores yet (they are asked once, when the game first starts). */
    static boolean shareAsked(Context c) {
        return prefs(c).contains("share_scores");
    }

    /** Share high scores with the leaderboard: false until the player says yes. */
    static boolean shareScores(Context c) {
        return prefs(c).getBoolean("share_scores", false);
    }

    static void setShareScores(Context c, boolean v) {
        prefs(c).edit().putBoolean("share_scores", v).apply();
    }

    /** The touch controls that can be moved and resized, each on its own: 0 the d-pad, 1 Action, 2 Magic, 3 Status, 4 Soft 1,
     *  5 Back, 6 Soft 2. */
    static final int CONTROL_GROUPS = 7;

    /** Where the player moved a group of touch controls, as a fraction of the screen's width and height from the default
     *  place; kept apart for portrait and landscape. */
    static float[] controlOffset(Context c, boolean landscape, int group) {
        String v = prefs(c).getString("ctl2_" + (landscape ? "land" : "port") + "_" + group, "");
        String[] parts = v.split(",");
        try {
            if (parts.length == 2) {
                float x = Float.parseFloat(parts[0]), y = Float.parseFloat(parts[1]);
                if (Float.isFinite(x) && Float.isFinite(y)) {                  // "NaN" must not hide a control for good
                    return new float[]{x, y};
                }
            }
        } catch (NumberFormatException e) {
            // a damaged value is the default place
        }
        return new float[]{0f, 0f};
    }

    static void setControlOffset(Context c, boolean landscape, int group, float x, float y) {
        prefs(c).edit().putString("ctl2_" + (landscape ? "land" : "port") + "_" + group,
                String.format(java.util.Locale.US, "%.4f,%.4f", x, y)).apply();
    }

    /** How much bigger (above 1) or smaller (below 1) the player made a control; 1 is the default size. */
    static float controlScale(Context c, boolean landscape, int group) {
        try {
            float v = Float.parseFloat(prefs(c).getString("ctlscale_" + (landscape ? "land" : "port") + "_" + group, "1"));
            if (Float.isFinite(v)) {
                return Math.max(0.5f, Math.min(2f, v));
            }
        } catch (NumberFormatException e) {
            // a damaged value is the default size
        }
        return 1f;
    }

    static void setControlScale(Context c, boolean landscape, int group, float v) {
        prefs(c).edit().putString("ctlscale_" + (landscape ? "land" : "port") + "_" + group,
                String.format(java.util.Locale.US, "%.3f", v)).apply();
    }

    /** Puts every touch control back where it started (both orientations). */
    static void resetControls(Context c) {
        SharedPreferences.Editor e = prefs(c).edit();
        for (String o : new String[]{"port", "land"}) {
            for (int g = 0; g < CONTROL_GROUPS; g++) {
                e.remove("ctl2_" + o + "_" + g);
                e.remove("ctlscale_" + o + "_" + g);
            }
        }
        e.apply();
    }

    static void restoreDefaults(Context c) {
        prefs(c).edit().clear().apply();
    }
}
