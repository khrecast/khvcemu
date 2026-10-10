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

    static void restoreDefaults(Context c) {
        prefs(c).edit().clear().apply();
    }
}
