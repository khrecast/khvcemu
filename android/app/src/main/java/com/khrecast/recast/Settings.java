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

    /** How the picture is enlarged (the desktop's four filters): 0 crisp pixels, 1 smooth, 2 sharp pixels, 3 Scale2x. */
    static final int FILTER_PIXELS = 0, FILTER_SMOOTH = 1, FILTER_SHARP = 2, FILTER_SCALE2X = 3;

    static int pictureFilter(Context c) {
        int v = prefs(c).getInt("filter", FILTER_PIXELS);
        return v >= 0 && v <= 3 ? v : FILTER_PIXELS;
    }

    static void setPictureFilter(Context c, int v) {
        prefs(c).edit().putInt("filter", v).apply();
    }

    /** The size of the game's own text in pixels (8 to 16, 11 as on the desktop); read when the game starts. */
    static int textSize(Context c) {
        int v = prefs(c).getInt("font_size", 11);
        return Math.max(8, Math.min(16, v));
    }

    static void setTextSize(Context c, int v) {
        prefs(c).edit().putInt("font_size", Math.max(8, Math.min(16, v))).apply();
    }

    /** The player's own saved mixes (a name and a music settings text each), in the order they were saved. */
    static java.util.LinkedHashMap<String, String> mixes(Context c) {
        java.util.LinkedHashMap<String, String> out = new java.util.LinkedHashMap<>();
        for (String line : prefs(c).getString("music_mixes", "").split("\n")) {
            int tab = line.indexOf('\t');
            if (tab > 0) {
                out.put(line.substring(0, tab), line.substring(tab + 1));
            }
        }
        return out;
    }

    /** A name fit to keep: no tabs or line breaks, trimmed, at most 40 characters; "" when nothing is left. */
    static String cleanMixName(String name) {
        String n = name == null ? "" : name.replaceAll("[\\t\\r\\n]+", " ").trim();
        return n.length() > 40 ? n.substring(0, 40).trim() : n;
    }

    static void saveMix(Context c, String name, String text) {
        java.util.LinkedHashMap<String, String> all = mixes(c);
        for (String existing : new java.util.ArrayList<>(all.keySet())) {
            if (existing.equalsIgnoreCase(name)) {
                all.remove(existing);                                    // "my piano" replaces "My piano"
            }
        }
        all.put(name, text);
        writeMixes(c, all);
    }

    /** Mixes (ready-made or the player's own) marked with a star on the Sound screen. */
    static java.util.Set<String> mixFavorites(Context c) {
        java.util.Set<String> out = new java.util.LinkedHashSet<>();
        for (String line : prefs(c).getString("music_favorites", "").split("\n")) {
            if (!line.trim().isEmpty()) {
                out.add(line.trim());
            }
        }
        return out;
    }

    static void toggleMixFavorite(Context c, String name) {
        java.util.Set<String> all = mixFavorites(c);
        if (!all.remove(name)) {
            all.add(name);
        }
        writeFavorites(c, all);
    }

    private static void writeFavorites(Context c, java.util.Set<String> all) {
        prefs(c).edit().putString("music_favorites", android.text.TextUtils.join("\n", all)).apply();
    }

    /** Gives one of the player's mixes another name (same place in the list, same star). */
    static void renameMix(Context c, String oldName, String newName) {
        java.util.LinkedHashMap<String, String> all = mixes(c);
        java.util.LinkedHashMap<String, String> renamed = new java.util.LinkedHashMap<>();
        for (java.util.Map.Entry<String, String> e : all.entrySet()) {
            renamed.put(e.getKey().equals(oldName) ? newName : e.getKey(), e.getValue());
        }
        writeMixes(c, renamed);
        java.util.Set<String> stars = mixFavorites(c);
        if (stars.remove(oldName)) {
            stars.add(newName);
            writeFavorites(c, stars);
        }
    }

    static void deleteMix(Context c, String name) {
        java.util.LinkedHashMap<String, String> all = mixes(c);
        all.remove(name);
        writeMixes(c, all);
        java.util.Set<String> stars = mixFavorites(c);
        if (stars.remove(name)) {
            writeFavorites(c, stars);
        }
    }

    private static void writeMixes(Context c, java.util.Map<String, String> all) {
        StringBuilder sb = new StringBuilder();
        for (java.util.Map.Entry<String, String> e : all.entrySet()) {
            sb.append(e.getKey()).append('\t').append(e.getValue()).append('\n');
        }
        prefs(c).edit().putString("music_mixes", sb.toString()).apply();
    }

    /** Flip phone mode: the game on a clamshell phone drawn round it (portrait only). */
    static boolean flipPhone(Context c) {
        return prefs(c).getBoolean("flip_phone", false);
    }

    /** The flip phone's body colors, by number (what FlipPhone.setColor takes). All are the plastics and metallics of 2005 handsets. */
    static final String[] FLIP_COLORS = {"Silver", "Graphite", "Sky blue", "Rose pink", "Champagne gold", "Red", "Re:Cast blue"};

    /** Which of FLIP_COLORS the flip phone wears (an earlier build kept only "graphite or not"). */
    static int flipColor(Context c) {
        android.content.SharedPreferences p = prefs(c);
        int v = p.contains("flip_color") ? p.getInt("flip_color", 0) : (p.getBoolean("flip_graphite", false) ? 1 : 0);
        return Math.max(0, Math.min(FLIP_COLORS.length - 1, v));
    }

    static void setFlipColor(Context c, int v) {
        prefs(c).edit().putInt("flip_color", v).remove("flip_graphite").apply();
    }

    static void setFlipPhone(Context c, boolean v) {
        prefs(c).edit().putBoolean("flip_phone", v).apply();
    }

    /** The flip phone with a thin frame round the screen, so the picture is bigger. */
    static boolean flipSmallBezel(Context c) {
        return prefs(c).getBoolean("flip_small_bezel", false);
    }

    static void setFlipSmallBezel(Context c, boolean v) {
        prefs(c).edit().putBoolean("flip_small_bezel", v).apply();
    }

    /** True once the player has answered the first-run question (smartphone style or flip phone style). */
    static boolean styleChosen(Context c) {
        return prefs(c).getBoolean("style_chosen", false);
    }

    static void setStyleChosen(Context c, boolean v) {
        prefs(c).edit().putBoolean("style_chosen", v).apply();
    }

    /** Soft 1 and Soft 2 on screen show the words the game itself puts above them. */
    static boolean liveSoftkeys(Context c) {
        return prefs(c).getBoolean("live_softkeys", true);
    }

    static void setLiveSoftkeys(Context c, boolean v) {
        prefs(c).edit().putBoolean("live_softkeys", v).apply();
    }

    /** Sharp text: the game's own text drawn at the screen's resolution instead of enlarged with the picture. */
    static boolean hiresText(Context c) {
        return prefs(c).getBoolean("hires_text", false);
    }

    static void setHiresText(Context c, boolean v) {
        prefs(c).edit().putBoolean("hires_text", v).apply();
    }

    /** The recording chosen for a tune on the Sound screen: the copy's path, or "" for none. */
    static String recFile(Context c, String tune) {
        String path = prefs(c).getString("rec_file_" + tune, "");
        return path.isEmpty() || new java.io.File(path).isFile() ? path : "";
    }

    /** A recording's own volume (1 = as it is); the Sound screen's slider, 0 to 4. */
    static float recGain(Context c, String tune) {
        return Math.max(0f, Math.min(4f, prefs(c).getFloat("rec_gain_" + tune, 1f)));
    }

    /** True when the game plays the recording in place of the tune. */
    static boolean recInGame(Context c, String tune) {
        return prefs(c).getBoolean("rec_ingame_" + tune, false);
    }

    static void setRecFile(Context c, String tune, String path) {
        prefs(c).edit().putString("rec_file_" + tune, path).apply();
    }

    static void setRecGain(Context c, String tune, float gain) {
        prefs(c).edit().putFloat("rec_gain_" + tune, gain).apply();
    }

    static void setRecInGame(Context c, String tune, boolean on) {
        prefs(c).edit().putBoolean("rec_ingame_" + tune, on).apply();
    }

    /** The recordings the game should play instead of tunes, as JSON for recast_app.start_game ("" when there are none). */
    static String musicFilesJson(Context c) {
        org.json.JSONObject all = new org.json.JSONObject();
        try {
            for (String[] tune : SoundSettings.TUNES) {
                String file = recFile(c, tune[0]);
                if (!file.isEmpty() && recInGame(c, tune[0])) {
                    all.put(tune[0], new org.json.JSONObject().put("path", file).put("gain", recGain(c, tune[0])));
                }
            }
        } catch (org.json.JSONException e) {
            return "";
        }
        return all.length() == 0 ? "" : all.toString();
    }

    static void restoreDefaults(Context c) {
        String mixes = prefs(c).getString("music_mixes", "");           // the player's own saved mixes are not a setting
        String stars = prefs(c).getString("music_favorites", "");       // nor are the stars on them
        boolean asked = styleChosen(c);                                 // and the first-run question is not asked again
        boolean shareAnswered = shareAsked(c);                          // nor the question about sharing scores (the default is: do not share)
        android.content.SharedPreferences.Editor keep = prefs(c).edit();
        java.util.Map<String, ?> before = prefs(c).getAll();
        java.util.Map<String, Object> recordings = new java.util.HashMap<>();   // the chosen recordings are the player's own files
        for (java.util.Map.Entry<String, ?> e : before.entrySet()) {
            if (e.getKey().startsWith("rec_")) {
                recordings.put(e.getKey(), e.getValue());
            }
        }
        keep.clear().putString("music_mixes", mixes).putString("music_favorites", stars).putBoolean("style_chosen", asked);
        if (shareAnswered) {
            keep.putBoolean("share_scores", false);
        }
        for (java.util.Map.Entry<String, Object> e : recordings.entrySet()) {
            Object v = e.getValue();
            if (v instanceof String) {
                keep.putString(e.getKey(), (String) v);
            } else if (v instanceof Boolean) {
                keep.putBoolean(e.getKey(), (Boolean) v);
            } else if (v instanceof Float) {
                keep.putFloat(e.getKey(), (Float) v);
            }
        }
        keep.apply();
    }
}
