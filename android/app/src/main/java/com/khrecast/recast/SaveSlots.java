package com.khrecast.recast;

import android.content.Context;

import org.json.JSONObject;

import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * The save slots on disk (files/data/states: slot1..slot9 and auto1..auto3, each a .khs state with a .png picture, the
 * desktop's own format and names), read without starting the game. The names here are the ones the core's
 * `StateSlots.parse` takes: "1".."9", "auto" (the newest autosave), "auto2", "auto3".
 */
final class SaveSlots {
    static final class Slot {
        final String name, label;
        final File file, thumb;
        final boolean exists;
        final long created;                    // milliseconds since 1970, from the file's header (else its modified time)

        Slot(String name, String label, File file, File thumb, boolean exists, long created) {
            this.name = name;
            this.label = label;
            this.file = file;
            this.thumb = thumb;
            this.exists = exists;
            this.created = created;
        }

        boolean isAuto() {
            return name.startsWith("auto");
        }

        boolean hasThumb() {
            return thumb.isFile();
        }
    }

    private static final byte[] MAGIC = {'K', 'H', 'V', 'C', 'E', 'M', 'U', 1};

    private SaveSlots() {
    }

    static File folder(Context context) {
        return new File(new File(context.getFilesDir(), "data"), "states");
    }

    /** Slots 1 to 9, then the three autosaves, filled or not. */
    static List<Slot> all(Context context) {
        File dir = folder(context);
        List<Slot> out = new ArrayList<>();
        for (int i = 1; i <= 9; i++) {
            out.add(slot(dir, String.valueOf(i), "Slot " + i, "slot" + i));
        }
        out.add(slot(dir, "auto", "The autosave", "auto1"));
        out.add(slot(dir, "auto2", "Auto2", "auto2"));
        out.add(slot(dir, "auto3", "Auto3", "auto3"));
        return out;
    }

    /** The most recently saved slot (an autosave counts), or null when there is none. */
    static Slot newest(Context context) {
        Slot best = null;
        for (Slot s : all(context)) {
            if (s.exists && (best == null || s.created > best.created)) {
                best = s;
            }
        }
        return best;
    }

    /** Deletes a slot's state and its picture. */
    static void delete(Context context, String name) {
        for (Slot s : all(context)) {
            if (s.name.equals(name)) {
                s.file.delete();
                s.thumb.delete();
            }
        }
    }

    private static Slot slot(File dir, String name, String label, String stem) {
        File file = new File(dir, stem + ".khs");
        File thumb = new File(dir, stem + ".png");
        boolean exists = file.isFile();
        long created = 0;
        if (exists) {
            created = headerCreated(file);
            if (created == 0) {
                created = file.lastModified();
            }
        }
        return new Slot(name, label, file, thumb, exists, created);
    }

    /** "created" (seconds since 1970) from the state's JSON header: the magic, a little-endian length, then the JSON. */
    private static long headerCreated(File f) {
        try (DataInputStream in = new DataInputStream(new FileInputStream(f))) {
            byte[] head = new byte[MAGIC.length + 4];
            in.readFully(head);
            for (int i = 0; i < MAGIC.length; i++) {
                if (head[i] != MAGIC[i]) {
                    return 0;
                }
            }
            int n = (head[8] & 0xFF) | (head[9] & 0xFF) << 8 | (head[10] & 0xFF) << 16 | (head[11] & 0xFF) << 24;
            if (n <= 0 || n > 64 * 1024) {
                return 0;
            }
            byte[] json = new byte[n];
            in.readFully(json);
            return (long) (new JSONObject(new String(json, "UTF-8")).optDouble("created", 0) * 1000);
        } catch (Throwable t) {
            return 0;
        }
    }
}
