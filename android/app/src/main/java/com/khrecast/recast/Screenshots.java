package com.khrecast.recast;

import android.content.ContentValues;
import android.content.Context;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Saves the game's picture as a PNG: into the phone's Pictures folder (Pictures/Re-Cast, through MediaStore, which needs no
 * permission on Android 10 and later; on older phones into the app's own Pictures folder). The picture is the game's own
 * 176 x 220 pixels enlarged by a whole number with hard edges, like the picture on screen.
 */
final class Screenshots {
    /** Android folder names cannot hold a colon, so "Re:Cast" is written "Re-Cast" here (as the macOS app is). */
    static final String FOLDER = "Re-Cast";
    static final int ZOOM = 4;

    private Screenshots() {
    }

    /** Writes the picture and returns where it went (for a message), or throws. */
    static String save(Context context, Bitmap game) throws IOException {
        // (a picture with sharp text is already made big by the screen: GameView.snapshot)
        int zoom = game.getWidth() > GameView.W ? 1 : ZOOM;
        Bitmap big = zoom == 1 ? game : Bitmap.createScaledBitmap(game, game.getWidth() * zoom, game.getHeight() * zoom, false);   // no smoothing
        String name = "Re-Cast_" + new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(new Date()) + ".png";
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
            values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + FOLDER);
            values.put(MediaStore.Images.Media.IS_PENDING, 1);
            Uri uri = context.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
            if (uri == null) {
                throw new IOException("the gallery would not take the picture");
            }
            try {
                try (OutputStream out = context.getContentResolver().openOutputStream(uri)) {
                    if (out == null || !big.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                        throw new IOException("could not write the picture");
                    }
                }
                values.clear();
                values.put(MediaStore.Images.Media.IS_PENDING, 0);
                context.getContentResolver().update(uri, values, null, null);
            } catch (IOException | RuntimeException e) {
                context.getContentResolver().delete(uri, null, null);     // no hidden or half-written picture left behind
                throw e;
            }
            return "Pictures/" + FOLDER;
        }
        File base = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES);
        if (base == null) {
            throw new IOException("no storage is available");
        }
        File dir = new File(base, FOLDER);
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("cannot create " + dir);
        }
        File file = new File(dir, name);
        try (FileOutputStream out = new FileOutputStream(file)) {
            if (!big.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                throw new IOException("could not write the picture");
            }
        }
        return file.getParent();
    }
}
