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

    static void restoreDefaults(Context c) {
        prefs(c).edit().clear().apply();
    }
}
