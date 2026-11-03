package com.khrecast.recast;

import android.os.Build;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;

/**
 * The few calls that need Android 8.0 (API 26) or later, with what Android 7.0 and 7.1 (API 24 and 25) do instead. On API 26 and later
 * these run exactly the code the app ran before minSdk went down to 24.
 */
final class Compat {
    private Compat() {
    }

    /** Moves `from` over `to`, replacing it (in the same folder: a rename, so the target is never half written). */
    static void moveReplacing(File from, File to) throws IOException {
        if (Build.VERSION.SDK_INT >= 26) {
            java.nio.file.Files.move(from.toPath(), to.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            return;
        }
        // java.nio.file is API 26. File.renameTo is rename(2) on Android, which replaces an existing file in one step.
        if (!from.renameTo(to)) {
            throw new IOException("rename failed: cannot move " + from + " to " + to);
        }
    }

    /** The whole file as bytes. */
    static byte[] readAllBytes(File file) throws IOException {
        if (Build.VERSION.SDK_INT >= 26) {
            return java.nio.file.Files.readAllBytes(file.toPath());
        }
        // read straight into one array of the file's size (a decoded recording is tens of MB, and Android 7 phones have little memory)
        try (RandomAccessFile in = new RandomAccessFile(file, "r")) {
            long size = in.length();
            if (size > Integer.MAX_VALUE - 8) {
                throw new IOException("too large to read: " + file);
            }
            byte[] data = new byte[(int) size];
            in.readFully(data);
            return data;
        }
    }
}
