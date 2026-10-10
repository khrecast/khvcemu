package com.khrecast.recast;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Copies the game files the player picked (a document tree, which gives content URIs, not paths) into the app's own
 * folder, where the Python core can open them, and checks them with khvcemu/gamefiles.py. Nothing is bundled in the app.
 */
final class GameInstaller {
    interface Progress {
        void onProgress(String text);
    }

    /** Written after a copy has passed the check: the app only starts the game when it exists. */
    static final String MARKER = ".installed";

    private static final int SEARCH_DEPTH = 3;

    private final Context context;
    private final ContentResolver resolver;
    private final Uri tree;
    private final String treeId;
    private int filesCopied;

    private GameInstaller(Context context, Uri tree) {
        this.context = context;
        this.resolver = context.getContentResolver();
        this.tree = tree;
        this.treeId = DocumentsContract.getTreeDocumentId(tree);
    }

    static File gameDir(Context context) {
        return new File(context.getFilesDir(), "game");
    }

    static boolean isInstalled(Context context) {
        return new File(gameDir(context), MARKER).isFile();
    }

    /** Deletes the copied game files (the player's saves and settings are kept). */
    static void remove(Context context) {
        deleteTree(gameDir(context));
    }

    /**
     * Copies and checks. Returns an empty list when the game is installed, else what is wrong, in words for the player.
     * Runs on the calling thread (a worker: this reads and writes a couple of megabytes).
     */
    static List<String> install(Context context, Uri tree, Progress progress) {
        List<String> problems = new ArrayList<>();
        File staging = new File(context.getFilesDir(), "game_new");
        File earlier = new File(context.getFilesDir(), "game_old");
        if (!gameDir(context).exists() && earlier.isDirectory()) {
            earlier.renameTo(gameDir(context));            // an earlier install was interrupted between its two renames
        }
        try {
            GameInstaller job = new GameInstaller(context, tree);
            progress.onProgress("Looking for the game files...");
            String root = job.findRoot(job.treeId, 0);
            if (root == null) {
                problems.add("This is not the game folder: it has no mif and mod folders inside.");
                return problems;
            }
            deleteTree(staging);
            if (!staging.mkdirs()) {
                problems.add("Could not make room in the app's storage.");
                return problems;
            }
            job.copyChildren(root, staging, progress, true);
            if (!Python.isStarted()) {                     // (the game is not running during an install, so no race)
                Python.start(new AndroidPlatform(context));
            }
            PyObject found = Python.getInstance().getModule("khvcemu.gamefiles").callAttr("problems", staging.getAbsolutePath());
            for (PyObject p : found.asList()) {
                problems.add(p.toString());
            }
            if (!problems.isEmpty()) {
                deleteTree(staging);
                return problems;
            }
            new File(staging, MARKER).createNewFile();     // inside the copy, so only a rename can fail below
            File game = gameDir(context);
            File old = new File(context.getFilesDir(), "game_old");
            deleteTree(old);
            if (game.exists() && !game.renameTo(old)) {
                problems.add("Could not replace the earlier game files.");
                deleteTree(staging);
                return problems;
            }
            if (!staging.renameTo(game)) {
                deleteTree(game);
                old.renameTo(game);                    // put the earlier files back
                deleteTree(staging);
                problems.add("Could not move the game files into place.");
                return problems;
            }
            deleteTree(old);
            progress.onProgress("Copied " + job.filesCopied + " files.");
        } catch (Throwable t) {
            deleteTree(staging);
            problems.add("Copying failed: " + t);
        }
        return problems;
    }

    /** The folder (document id) that has both a mif and a mod folder inside, the picked one or a few levels down. */
    private String findRoot(String docId, int depth) {
        List<String[]> kids = children(docId);
        boolean mif = false, mod = false;
        for (String[] k : kids) {
            if (isDir(k)) {
                mif |= k[1].equalsIgnoreCase("mif");
                mod |= k[1].equalsIgnoreCase("mod");
            }
        }
        if (mif && mod) {
            return docId;
        }
        if (depth >= SEARCH_DEPTH) {
            return null;
        }
        for (String[] k : kids) {
            if (isDir(k)) {
                String found = findRoot(k[0], depth + 1);
                if (found != null) {
                    return found;
                }
            }
        }
        return null;
    }

    /** Copies the mif and mod folders, and the game saves (savegame(world).dat) found beside them. */
    private void copyChildren(String docId, File into, Progress progress, boolean top) throws IOException {
        for (String[] k : children(docId)) {
            String name = cleanName(k[1]);
            if (name == null) {
                continue;                                  // a name that could leave the folder (".." and the like)
            }
            if (isDir(k)) {
                if (!top || name.equalsIgnoreCase("mif") || name.equalsIgnoreCase("mod")) {
                    File dir = new File(into, name.toLowerCase(Locale.ROOT));
                    if (!dir.isDirectory() && !dir.mkdirs()) {
                        throw new IOException("cannot create " + dir);
                    }
                    copyChildren(k[0], dir, progress, false);
                }
            } else if (!top || (name.toLowerCase(Locale.ROOT).startsWith("savegame(") && name.toLowerCase(Locale.ROOT).endsWith(".dat"))) {
                String low = name.toLowerCase(Locale.ROOT);
                boolean game = low.endsWith(".mif") || low.endsWith(".mod") || low.endsWith(".sig");
                copyFile(k[0], new File(into, game ? low : name));   // the module scan wants lower-case names
                if (++filesCopied % 25 == 0) {
                    progress.onProgress("Copying... " + filesCopied + " files");
                }
            }
        }
    }

    /** A file or folder name that is safe to create inside our own folder, or null (empty, ".", "..", a path, a NUL). */
    static String cleanName(String name) {
        if (name == null || name.isEmpty() || name.equals(".") || name.equals("..")
                || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.indexOf((char) 0) >= 0) {
            return null;
        }
        return name;
    }

    private void copyFile(String docId, File out) throws IOException {
        Uri uri = DocumentsContract.buildDocumentUriUsingTree(tree, docId);
        try (InputStream in = resolver.openInputStream(uri); OutputStream os = new FileOutputStream(out)) {
            if (in == null) {
                throw new IOException("cannot read " + out.getName());
            }
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                os.write(buf, 0, n);
            }
        }
    }

    /** {document id, display name, mime type} of each child. */
    private List<String[]> children(String docId) {
        List<String[]> out = new ArrayList<>();
        Uri uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
        String[] cols = {DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE};
        try (Cursor c = resolver.query(uri, cols, null, null, null)) {
            while (c != null && c.moveToNext()) {
                if (c.getString(0) != null && c.getString(1) != null && c.getString(2) != null) {
                    out.add(new String[]{c.getString(0), c.getString(1), c.getString(2)});
                }
            }
        }
        return out;
    }

    private static boolean isDir(String[] kid) {
        return DocumentsContract.Document.MIME_TYPE_DIR.equals(kid[2]);
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                deleteTree(k);
            }
        }
        f.delete();
    }
}
