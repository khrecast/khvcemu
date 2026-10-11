package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowInsets;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The game's 176x220 picture (enlarged with the nearest pixel, like the desktop's "crisp pixels") and, under it,
 * the phone's keys as touch controls: a pad for the four directions (diagonals work), Action, Magic, Status, the
 * two softkeys and Back. Several fingers at once are fine. A tap on the picture itself is passed on to the game
 * (in game pixels), which turns it into the keys of whatever button it landed on (khvcemu/tapmap.py). Everything is
 * laid out inside the area the system bars leave free, so nothing is hidden behind the navigation bar.
 */
public class GameView extends View {
    public static final int W = 176, H = 220;

    /** Called for every key that goes down or up (phone key names such as UP, SELECT, STAR, 0, SOFT1). */
    public interface KeySink {
        void key(String name, boolean down);
    }

    /** Called for a tap on the picture, in game pixels (0 to 176, 0 to 220). */
    public interface TapSink {
        void tap(float x, float y);
    }

    private static class Button {
        final String key, label;
        final RectF r = new RectF();
        final boolean round;

        Button(String key, String label, boolean round) {
            this.key = key;
            this.label = label;
            this.round = round;
        }
    }

    private final Bitmap frame = Bitmap.createBitmap(W, H, Bitmap.Config.RGB_565);
    private final Paint pixels = new Paint();                 // no filtering: crisp pixels
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final ControlSkin skin;                           // how the touch controls look
    private final Rect src = new Rect(0, 0, W, H);
    private final RectF dst = new RectF();
    private final List<Button> buttons = new ArrayList<>();
    private final Set<String> held = new HashSet<>();
    private float padX, padY, padR, statusY;
    // moving the controls: 0 the d-pad, 1 Action/Magic/Status, 2 the softkey bars. Offsets are fractions of the screen.
    private final float[][] offset = new float[Settings.CONTROL_GROUPS][2];
    private final float[] scale = new float[Settings.CONTROL_GROUPS];      // 1 = the default size
    private int pinchPointer = -1;
    private float pinchStartDist, pinchStartScale;
    private final RectF resetRect = new RectF(), modeRect = new RectF();   // the editor's two buttons: put back, and one thumb or two
    private boolean offsetLandscape, offsetTwoThumb, offsetsLoaded;
    // the two-thumb layout: four arrow keys, each a control of its own (groups 0, 7, 8 and 9)
    private boolean twoThumb;
    private final RectF upR = new RectF(), downR = new RectF(), leftR = new RectF(), rightR = new RectF();
    private float colL0, colL1, colR0, colR1, areaT, areaB;                 // the room the controls have: two columns and their height
    private volatile boolean editing;
    private boolean needDown;                    // after editing: ignore a finger that is still down from before
    private int grabbed = -1, grabPointer = -1;
    private float grabX, grabY;
    private final float[] grabStart = new float[2];
    private final Paint outline = new Paint(Paint.ANTI_ALIAS_FLAG);
    private android.graphics.DashPathEffect dashes;
    private int insetTop, insetBottom, insetLeft, insetRight;  // the system bars, in pixels
    private Runnable editEnded;                  // told when the layout (not the player) ends the controls editor
    private boolean flipMode, flipSmallBezel;
    private int flipColor;
    private FlipPhone flip;
    private int filter = Settings.FILTER_PIXELS;
    private final Paint smoothPaint = new Paint(Paint.FILTER_BITMAP_FLAG);   // bilinear: for the soft last step of a filter
    private Bitmap work;                                    // the picture enlarged by a whole number (Sharp, Scale2x)
    private Canvas workCanvas;
    private int[] pixelsIn, pixelsA, pixelsB;
    private int pictureScale = Settings.FIT;                // see Settings: FIT, LARGEST or a whole number of pixels
    private String status = "";
    private KeySink sink;
    private TapSink tapSink;
    private boolean hasFrame;
    private final float slop;
    // a possible tap on the picture: where and when the finger went down, and which finger
    private int tapPointer = -1;
    private float tapX, tapY;
    private long tapTime;

    public GameView(Context context) {
        super(context);
        slop = ViewConfiguration.get(context).getScaledTouchSlop();
        skin = new ControlSkin(context);
        pixels.setFilterBitmap(false);
        pixels.setAntiAlias(false);
        text.setColor(Color.WHITE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        buttons.add(new Button("SOFT1", "Soft 1", false));
        buttons.add(new Button("CLR", "Back", false));
        buttons.add(new Button("SOFT2", "Soft 2", false));
        buttons.add(new Button("SELECT", "Action", true));
        buttons.add(new Button("STAR", "Magic", true));
        buttons.add(new Button("0", "Status", true));
        java.util.Arrays.fill(scale, 1f);
        setBackgroundColor(Color.BLACK);
    }

    public void setKeySink(KeySink sink) {
        this.sink = sink;
    }

    /** Flip phone mode (portrait only): the game on a clamshell phone with a keypad. Takes effect at once. */
    public void setEditEndedListener(Runnable r) {
        editEnded = r;
    }

    /** The two-thumb layout (smartphone look): forward and back, Magic and Status on the left; turn and Action on the right. */
    public void setTwoThumb(boolean on) {
        if (on != twoThumb) {
            twoThumb = on;
            releaseAll();
            offsetsLoaded = false;                                          // it has its own saved places
            layoutControls(getWidth(), getHeight());
            postInvalidate();
        }
    }

    public void setFlipSmallBezel(boolean on) {
        if (on != flipSmallBezel) {
            flipSmallBezel = on;
            if (flip != null) {
                flip.setSmallBezel(on);
                if (getWidth() > 0) {
                    layoutControls(getWidth(), getHeight());
                }
            }
            postInvalidate();
        }
    }

    public void setFlipColor(int color) {
        flipColor = color;
        if (flip != null) {
            flip.setColor(color);
        }
        postInvalidate();
    }

    public void setFlipMode(boolean on) {
        if (on != flipMode) {
            flipMode = on;
            releaseAll();
            layoutControls(getWidth(), getHeight());
            postInvalidate();
        }
    }

    /** True while the flip phone is what is on screen (the mode is on and the phone is upright). */
    public boolean isFlipActive() {
        return flipMode && getWidth() > 0 && getWidth() <= getHeight() && flip != null;
    }

    private java.util.Set<String> allDown() {
        java.util.Set<String> all = new HashSet<>(held);
        all.addAll(padHeld.keySet());
        return all;
    }

    /** How the picture is enlarged (Settings.FILTER_*): takes effect at once. */
    public void setFilter(int f) {
        if (f != filter) {
            filter = f;
            postInvalidate();
        }
    }

    private boolean epxPending;                                   // Scale2x: the pixels are copied under the lock, the work is not
    private final Rect workRect = new Rect();

    /** Draws the game's picture into `dst` with the chosen filter. Called with `frame` locked, so it only copies for Scale2x. */
    private void drawPicture(Canvas c) {
        epxPending = false;
        if (filter == Settings.FILTER_SMOOTH) {
            c.drawBitmap(frame, src, dst, smoothPaint);
        } else if (filter == Settings.FILTER_SHARP) {
            // crisp blocks of the largest whole size that fits, then a soft step for the last fraction
            int n = Math.max(1, Math.min((int) (dst.width() / W), (int) (dst.height() / H)));
            if (n == 1) {
                c.drawBitmap(frame, src, dst, smoothPaint);
            } else {
                ensureWork(W * n, H * n);
                workRect.set(0, 0, W * n, H * n);
                workCanvas.drawBitmap(frame, src, workRect, pixels);
                c.drawBitmap(work, null, dst, smoothPaint);
            }
        } else if (filter == Settings.FILTER_SCALE2X) {
            if (scale2xTimes() == 0) {
                c.drawBitmap(frame, src, dst, smoothPaint);          // under 2x there is nothing to double
            } else {
                if (pixelsIn == null) {
                    pixelsIn = new int[W * H];
                }
                frame.getPixels(pixelsIn, 0, W, 0, 0, W, H);        // the rest happens after the lock is let go
                epxPending = true;
            }
        } else {
            c.drawBitmap(frame, src, dst, pixels);
        }
    }

    /** How many times Scale2x doubles the picture: while twice the size still fits in both directions, twice at most. */
    private int scale2xTimes() {
        int times = 0;
        while (times < 2 && (W << (times + 1)) <= dst.width() && (H << (times + 1)) <= dst.height()) {
            times++;
        }
        return times;
    }

    /** Scale2x (EPX) on the pixels copied by drawPicture, then a soft step to the picture's size. Not under the frame lock. */
    private void finishScale2x(Canvas c) {
        int times = scale2xTimes();
        int w = W, h = H;
        int[] from = pixelsIn;
        for (int i = 0; i < times; i++) {
            int[] to = i == 0 ? bufferA(w * 2 * h * 2) : bufferB(w * 2 * h * 2);
            epx(from, w, h, to);
            from = to;
            w *= 2;
            h *= 2;
        }
        ensureWork(w, h);
        work.setPixels(from, 0, w, 0, 0, w, h);
        c.drawBitmap(work, null, dst, smoothPaint);
    }

    private int[] bufferA(int n) {
        if (pixelsA == null || pixelsA.length < n) {
            pixelsA = new int[n];
        }
        return pixelsA;
    }

    private int[] bufferB(int n) {
        if (pixelsB == null || pixelsB.length < n) {
            pixelsB = new int[n];
        }
        return pixelsB;
    }

    private void ensureWork(int w, int h) {
        if (work == null || work.getWidth() != w || work.getHeight() != h) {
            work = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
            workCanvas = new Canvas(work);
        }
    }

    /** Scale2x (EPX): every pixel becomes four, each taking a neighbor's color where two neighbors agree at a corner. */
    private static void epx(int[] in, int w, int h, int[] out) {
        int ow = w * 2;
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                int p = in[y * w + x];
                int a = y > 0 ? in[(y - 1) * w + x] : p;           // up
                int b = x < w - 1 ? in[y * w + x + 1] : p;         // right
                int cc = x > 0 ? in[y * w + x - 1] : p;            // left
                int d = y < h - 1 ? in[(y + 1) * w + x] : p;       // down
                int p1 = p, p2 = p, p3 = p, p4 = p;
                if (cc == a && cc != d && a != b) {
                    p1 = a;
                }
                if (a == b && a != cc && b != d) {
                    p2 = b;
                }
                if (d == cc && d != b && cc != a) {
                    p3 = cc;
                }
                if (b == d && b != a && d != cc) {
                    p4 = d;
                }
                int o = y * 2 * ow + x * 2;
                out[o] = p1;
                out[o + 1] = p2;
                out[o + ow] = p3;
                out[o + ow + 1] = p4;
            }
        }
    }

    /** Picture size (Settings.FIT, Settings.LARGEST or 1, 2, 3...): takes effect at once. */
    public void setPictureScale(int scale) {
        if (scale != pictureScale) {
            pictureScale = scale;
            layoutControls(getWidth(), getHeight());
            postInvalidate();
        }
    }

    public void setTapSink(TapSink sink) {
        this.tapSink = sink;
    }

    /** New picture: 176*220 little-endian RGB565 pixels. Called from a worker thread. */
    public void setFrame(byte[] rgb565) {
        setFrame(rgb565, null);
    }

    /**
     * New picture and, with sharp text, the strings the game drew on it (JSON from recast_app.frame_text; the picture then
     * has those strings taken out). Both change together. null means no sharp text.
     */
    public void setFrame(byte[] rgb565, String textJson) {
        if (rgb565 == null || rgb565.length != W * H * 2) {
            return;
        }
        List<TextItem> parsed = textJson != null && textJson.equals(lastJson) ? items : parseItems(textJson);   // (same strings: no new parse)
        lastJson = textJson;
        synchronized (frame) {
            frame.copyPixelsFromBuffer(ByteBuffer.wrap(rgb565));
            hasFrame = true;
            items = parsed;
        }
        postInvalidate();
    }

    public void setSharpText(boolean on) {
        sharpOn = on;
    }

    /**
     * The words the game shows at the bottom left (left = true) or bottom right of its screen, where its softkey labels sit
     * ("Select", "Back", "Continue"...), or null when there are none. Read from the strings the core drew. They are drawn at y 199;
     * the last entry of the title menu ("Quit") starts near y 190, so it must not count.
     */
    private String softkeyWord(boolean left) {
        String best = null;
        float bestY = -1;
        for (TextItem it : items) {
            float mid = (it.bx0 + it.bx1) / 2f;
            if (it.y >= 195 && it.by0 >= 195 && it.bx1 - it.bx0 < W * 0.45f && (mid < W * 0.45f ? left : mid > W * 0.55f && !left) && it.by0 >= bestY) {
                String word = it.text.trim();
                if (!word.isEmpty() && word.length() <= 14) {         // a key's word is short: not a line of dialogue
                    best = word;
                    bestY = it.by0;
                }
            }
        }
        return best;
    }

    /**
     * The word in the banner the game slides in at the top of its screen to say what Action will do ("Open", "Attack", "Grab"...),
     * or null when there is none: a single short word of letters, on a pink or red banner, in the top strip. The other banners ("Munny = 11", "Game Saved",
     * "Obtained Gem 1 of 4") have digits or spaces, so they do not count. The newest one drawn wins.
     */
    private String actionWord() {
        String best = null;
        for (TextItem it : items) {
            String word = it.text.trim();
            int red = it.back >> 16 & 0xFF, green = it.back >> 8 & 0xFF;
            // (the banner slides in from y -11 and rests at y 6, its box ending at row 20)
            boolean pinkOrRed = red >= 140 && green * 10 <= red * 7;           // the action banner is pink or red; the info banners are yellow (the text on them is dark)
            if (pinkOrRed && it.y > -20 && it.y <= 8 && it.by1 <= 22 && it.by1 > it.by0 && word.length() >= 3 && word.length() <= 10 && word.matches("[A-Za-z]+")) {
                best = word;
            }
        }
        if (best == null && onMenuScreen()) {
            return "Enter";                                          // on a menu (and a dialogue page) the key picks or goes on
        }
        return best;
    }

    /**
     * True on one of the game's menus (the title menu, Options, the status screen...): they draw their entries as two or more text
     * lines across the middle of the screen, which the 3D world never does (its text is a banner at the top and the softkey words at
     * the bottom).
     */
    private boolean onMenuScreen() {
        int lines = 0;
        for (TextItem it : items) {
            if (it.by0 >= 25 && it.by1 <= 186 && it.text.trim().length() >= 3) {
                lines++;
            }
        }
        return lines >= 2;
    }

    /** One string the game drew, to be drawn again sharp. */
    private static final class TextItem {
        String text;
        boolean bold;
        int x, y, w, h, color, back, bx0, by0, bx1, by1;
    }

    private volatile List<TextItem> items = java.util.Collections.emptyList();
    private volatile boolean sharpOn;                            // draw the strings sharp (Options), not only read them
    private String lastJson;                                     // the pump thread's
    private final Paint sharpPaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.SUBPIXEL_TEXT_FLAG);
    private final java.util.HashMap<String, float[]> measured = new java.util.HashMap<>();   // text and weight -> width, height at 100

    private static List<TextItem> parseItems(String json) {
        if (json == null || json.length() < 3) {
            return java.util.Collections.emptyList();
        }
        List<TextItem> out = new ArrayList<>();
        try {
            org.json.JSONArray all = new org.json.JSONArray(json);
            for (int i = 0; i < all.length(); i++) {
                org.json.JSONObject o = all.getJSONObject(i);
                TextItem it = new TextItem();
                it.text = o.getString("t");
                int font = o.getInt("f");
                it.bold = font == 0x8001 || font == 0x8002;      // AEE_FONT_BOLD and AEE_FONT_LARGE (khvcemu/display.py)
                it.x = o.getInt("x");
                it.y = o.getInt("y");
                it.w = o.getInt("w");
                it.h = o.getInt("h");
                int g = o.optInt("g", 0);
                it.back = 0xFF000000 | ((((g >> 11) & 31) * 255 / 31) << 16) | ((((g >> 5) & 63) * 255 / 63) << 8) | ((g & 31) * 255 / 31);
                int c = o.getInt("c");
                it.color = 0xFF000000 | ((((c >> 11) & 31) * 255 / 31) << 16) | ((((c >> 5) & 63) * 255 / 63) << 8) | ((c & 31) * 255 / 31);
                org.json.JSONArray b = o.getJSONArray("b");
                it.bx0 = b.getInt(0);
                it.by0 = b.getInt(1);
                it.bx1 = b.getInt(2);
                it.by1 = b.getInt(3);
                out.add(it);
            }
        } catch (org.json.JSONException e) {
            return java.util.Collections.emptyList();
        }
        return out;
    }

    /** Draws the strings sharp over a picture drawn into `d`: each one in the system font, fitted to the box the game gave it. */
    private void drawSharpText(Canvas c, RectF d, List<TextItem> list) {          // UI thread only (it shares one Paint and a cache)
        if (list.isEmpty() || !sharpOn) {
            return;
        }
        float kx = d.width() / W, ky = d.height() / H;
        for (TextItem it : list) {
            sharpPaint.setTypeface(it.bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
            sharpPaint.setTextSize(100f);
            String key = (it.bold ? "b" : "n") + it.text;
            float[] m = measured.get(key);
            if (m == null) {
                Paint.FontMetrics fm = sharpPaint.getFontMetrics();
                m = new float[]{Math.max(1f, sharpPaint.measureText(it.text)), fm.descent - fm.ascent, -fm.ascent};
                if (measured.size() > 800) {
                    measured.clear();
                }
                measured.put(key, m);
            }
            float sx = it.w * kx / m[0], sy = it.h * ky / m[1];
            if (sx < 0.8f * sy || sx > 1.25f * sy) {
                sx = sy = Math.min(sx, sy);                      // a font whose shape differs much: keep its own shape
            }
            sharpPaint.setColor(it.color);
            c.save();
            c.clipRect(d.left + it.bx0 * kx - 1, d.top + it.by0 * ky - 1, d.left + it.bx1 * kx + 1, d.top + it.by1 * ky + 1);
            c.translate(d.left + it.x * kx, d.top + it.y * ky);
            c.scale(sx, sy);
            c.drawText(it.text, 0, m[2], sharpPaint);
            c.restore();
        }
    }

    /** A copy of the game's current picture (176 x 220), or null before the first frame. */
    public Bitmap snapshot() {
        synchronized (frame) {
            if (!hasFrame) {
                return null;
            }
            if (items.isEmpty() || !sharpOn) {
                return frame.copy(Bitmap.Config.ARGB_8888, false);
            }
            int zoom = 4;                                        // sharp text: the picture enlarged here, with the strings drawn on it
            Bitmap big = Bitmap.createBitmap(W * zoom, H * zoom, Bitmap.Config.ARGB_8888);
            Canvas bc = new Canvas(big);
            RectF all = new RectF(0, 0, W * zoom, H * zoom);
            bc.drawBitmap(frame, null, all, pixels);
            drawSharpText(bc, all, items);
            return big;
        }
    }

    public void setStatus(String s) {
        status = s;
        postInvalidate();
    }

    @SuppressWarnings("deprecation")
    @Override
    public WindowInsets onApplyWindowInsets(WindowInsets insets) {
        // the navigation bar, the gesture area and the status bar: nothing of ours may sit behind them
        insetTop = insets.getSystemWindowInsetTop();
        insetBottom = insets.getSystemWindowInsetBottom();
        insetLeft = insets.getSystemWindowInsetLeft();
        insetRight = insets.getSystemWindowInsetRight();
        layoutControls(getWidth(), getHeight());
        invalidate();
        return super.onApplyWindowInsets(insets);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        if (flipMode && (w <= h) != (oldw <= oldh)) {
            releaseAll();                                           // the keys under a finger change with the layout
        }
        layoutControls(w, h);
    }

    /** Landscape: the picture in the middle at the full height, the pad and the softkeys at its left, the buttons and
     *  the other softkey at its right, so both thumbs rest at the sides of the phone. */
    private void layoutLandscape(int w, int h) {
        float left = insetLeft, right = w - insetRight, width = right - left;
        float top = insetTop, bottom = h - insetBottom, free = bottom - top;
        float gh = free * 0.93f;                                       // the status line sits under the picture
        if (pictureScale != Settings.FIT) {
            int most = Math.max(1, (int) Math.floor(gh / H));
            gh = H * (pictureScale == Settings.LARGEST ? most : Math.min(pictureScale, most));
        }
        float gw = gh * W / H;
        float gx = left + (width - gw) / 2f;
        dst.set(gx, top + free * 0.01f, gx + gw, top + free * 0.01f + gh);
        statusY = bottom - free * 0.008f;

        float leftW = Math.max(0f, gx - left), rightW = Math.max(0f, right - (gx + gw));
        float lc = left + leftW / 2f, rc = gx + gw + rightW / 2f;     // the middle of each side
        float softH = free * 0.12f, softTop = top + free * 0.04f, gap = leftW * 0.03f;
        buttons.get(0).r.set(left + gap, softTop, lc - gap, softTop + softH);                      // SOFT1
        buttons.get(1).r.set(lc + gap, softTop, left + leftW - gap, softTop + softH);              // CLR
        buttons.get(2).r.set(rc - rightW * 0.45f, softTop, rc + rightW * 0.45f, softTop + softH);  // SOFT2

        float areaTop = softTop + softH + free * 0.03f, areaBottom = bottom - free * 0.05f;
        float area = areaBottom - areaTop;
        colL0 = left;
        colL1 = gx;
        colR0 = gx + gw;
        colR1 = right;
        areaT = areaTop;
        areaB = areaBottom;
        padR = Math.min(leftW * 0.44f, area * 0.46f);
        padX = lc;
        padY = areaBottom - padR;
        float cy = areaTop + area / 2f;
        // Action in front, Magic and Status up and to either side of it (about 37 degrees from straight up), all touching: the
        // cluster is 3.7 radii wide and 3.4 tall, so the buttons are as big as the side of the picture allows
        float big = Math.min(rightW * 0.255f, area * 0.285f);
        float ax = rc, ay = cy + 0.535f * big;                                  // (centers the cluster vertically)
        placeButtons(ax, ay, big,                                               // Action
                ax - 0.75f * big, ay - big,                                     // Magic
                ax + 0.75f * big, ay - big);                                    // Status
    }

    /** The picture at the top of the free area, the softkeys under it, the pad and buttons in what is left. */
    private void layoutControls(int w, int h) {
        if (w == 0 || h == 0) {
            return;
        }
        if (flipMode && w <= h) {
            if (editing) {
                setEditing(false);                                  // the editor's boxes are not drawn in the flip phone
                if (editEnded != null) {
                    editEnded.run();                                // so the game is not left held
                }
            }
            if (flip == null) {
                flip = new FlipPhone(getContext());
                flip.setColor(flipColor);
                flip.setSmallBezel(flipSmallBezel);
            }
            flip.layout(insetLeft, insetTop, w - insetRight, h - insetBottom, dst);
            statusY = h - insetBottom - (h - insetTop - insetBottom) * 0.004f;
            return;                                                 // the phone has its own keys: no moved or resized controls
        }
        layoutBase(w, h);
        if (twoThumb) {
            layoutTwoThumb();
        }
        boolean landscape = w > h;
        if (!offsetsLoaded || offsetLandscape != landscape || offsetTwoThumb != twoThumb) {   // each has its own positions
            for (int g = 0; g < Settings.CONTROL_GROUPS; g++) {
                float[] saved = Settings.controlOffset(getContext(), landscape, twoThumb, g);
                offset[g][0] = saved[0];
                offset[g][1] = saved[1];
                scale[g] = Settings.controlScale(getContext(), landscape, twoThumb, g);
            }
            offsetLandscape = landscape;
            offsetTwoThumb = twoThumb;
            offsetsLoaded = true;
        }
        applyOffsets(w, h);
    }

    /**
     * The two-thumb places: the left column holds Magic and Status in a row with the forward and back keys under them, the right column
     * Action with the turn keys under it. Everything is kept apart so that each thumb has its own keys and neither has to turn and
     * move at once.
     */
    private void layoutTwoThumb() {
        float cwL = colL1 - colL0, cwR = colR1 - colR0, ch = areaB - areaT;
        float narrow = Math.max(1f, Math.min(cwL, cwR));
        final float bigger = 1.18f;                                         // all of these were made about 18 percent bigger after a first try
        float rs = Math.min(narrow * 0.17f, ch * 0.12f) * bigger;           // Magic and Status
        float bs = Math.min(narrow * 0.30f, ch * 0.22f) * bigger;           // one arrow key
        float ra = Math.min(cwR * 0.26f, ch * 0.24f) * bigger;              // Action
        float gap = bs * 0.12f;
        float lcx = (colL0 + colL1) / 2f, rcx = (colR0 + colR1) / 2f;
        float rowY = areaT + rs + ch * 0.04f;
        setCircle(buttons.get(4), lcx - rs * 1.15f, rowY, rs);              // Magic
        setCircle(buttons.get(5), lcx + rs * 1.15f, rowY, rs);              // Status
        setCircle(buttons.get(3), rcx, areaT + ra + ch * 0.03f, ra);        // Action
        // the arrow keys start as two pairs (the forward/back pair at the left, the turn pair at the right, both on the bottom edge of
        // the room); each key is then moved and sized on its own like every other control
        float pairH = 2 * bs + gap, gm = pairH * 0.06f, hm = (pairH - gm) / 2f;
        upR.set(lcx - bs / 2f, areaB - pairH, lcx + bs / 2f, areaB - pairH + hm);
        downR.set(lcx - bs / 2f, areaB - hm, lcx + bs / 2f, areaB);
        float gt = pairH * 0.06f, wt = (pairH - gt) / 2f;
        leftR.set(rcx - pairH / 2f, areaB - bs, rcx - pairH / 2f + wt, areaB);
        rightR.set(rcx + pairH / 2f - wt, areaB - bs, rcx + pairH / 2f, areaB);
    }

    /** Groups 7 to 9 (the back key and the two turn keys) exist only in the two-thumb layout. */
    private boolean groupActive(int g) {
        return g < 7 || twoThumb;
    }

    /** The key of the two-thumb layout that a group is: 0 forward, 7 back, 8 turn left, 9 turn right. */
    private RectF keyRect(int g) {
        return g == 0 ? upR : g == 7 ? downR : g == 8 ? leftR : rightR;
    }

    /** The bounds of a group of controls, in pixels. */
    private RectF groupBounds(int g) {
        RectF r = new RectF();
        if (twoThumb && (g == 0 || g >= 7)) {
            r.set(keyRect(g));
        } else if (g >= 7) {
            // (not in this layout: an empty box)
        } else if (g == 0) {
            r.set(padX - padR, padY - padR, padX + padR, padY + padR);
        } else {
            r.set(buttons.get(buttonOf(g)).r);                             // every other group is one button
        }
        return r;
    }

    /** The index in `buttons` of a group above 0: 1 Action, 2 Magic, 3 Status (buttons 3 to 5), 4 Soft 1, 5 Back, 6 Soft 2. */
    private static int buttonOf(int group) {
        return group <= 3 ? group + 2 : group - 4;
    }

    /**
     * Applies what the player chose to each control: first its size (about its default centre, never bigger than the free
     * area), then its position (kept inside the free area). The values actually used are written back, so what is saved
     * and what is shown agree.
     */
    private void applyOffsets(int w, int h) {
        float freeW = Math.max(1f, w - insetLeft - insetRight), freeH = Math.max(1f, h - insetTop - insetBottom);
        for (int g = 0; g < Settings.CONTROL_GROUPS; g++) {
            if (!groupActive(g)) {
                continue;
            }
            RectF b = groupBounds(g);
            float floor = Math.max(0.5f, Math.min(1f, dp(44) / Math.max(1f, Math.min(b.width(), b.height()))));   // thumb-sized
            float s = Math.max(floor, Math.min(2f, scale[g]));
            s = Math.min(s, Math.min(freeW / Math.max(1f, b.width()), freeH / Math.max(1f, b.height())));
            scale[g] = s;
            if (Math.abs(s - 1f) > 0.0005f) {
                if (twoThumb && (g == 0 || g >= 7)) {
                    RectF r = keyRect(g);
                    float cx = r.centerX(), cy = r.centerY(), hw = r.width() / 2f * s, hh = r.height() / 2f * s;
                    r.set(cx - hw, cy - hh, cx + hw, cy + hh);
                } else if (g == 0) {
                    padR *= s;
                } else {
                    RectF r = buttons.get(buttonOf(g)).r;
                    float cx = r.centerX(), cy = r.centerY(), hw = r.width() / 2f * s, hh = r.height() / 2f * s;
                    r.set(cx - hw, cy - hh, cx + hw, cy + hh);
                }
            }
        }
        for (int g = 0; g < Settings.CONTROL_GROUPS; g++) {                // (always: a bigger control may need pulling in)
            if (!groupActive(g)) {
                continue;
            }
            RectF b = groupBounds(g);
            float dx = offset[g][0] * w, dy = offset[g][1] * h;
            dx = Math.max(insetLeft - b.left, Math.min(w - insetRight - b.right, dx));
            dy = Math.max(insetTop - b.top, Math.min(h - insetBottom - b.bottom, dy));
            offset[g][0] = dx / w;
            offset[g][1] = dy / h;
            if (twoThumb && (g == 0 || g >= 7)) {
                keyRect(g).offset(dx, dy);
            } else if (g == 0) {
                padX += dx;
                padY += dy;
            } else {
                buttons.get(buttonOf(g)).r.offset(dx, dy);
            }
        }
    }

    /** Edit mode: the controls can be dragged, and press nothing. The positions are saved as they are dropped. */
    public void setEditing(boolean on) {
        if (on) {
            releaseAll();
        }
        if (editing && !on) {
            needDown = true;                                               // a finger still down must not press keys
        }
        editing = on;
        grabbed = -1;
        grabPointer = -1;
        invalidate();
    }

    public boolean isEditing() {
        return editing;
    }

    /**
     * One finger moves one control (it is remembered by its id): the control goes to where it started plus how far that
     * finger has moved. A second finger on the screen resizes it: the control grows and shrinks with the distance between the
     * two fingers. The "Put the controls back" button resets every control.
     */
    private boolean onEditTouch(MotionEvent e) {
        int action = e.getActionMasked();
        switch (action) {
            case MotionEvent.ACTION_DOWN: {
                grabbed = -1;
                pinchPointer = -1;
                grabPointer = e.getPointerId(0);
                float x = e.getX(), y = e.getY();
                updateResetRect();
                if (resetRect.contains(x, y)) {
                    new android.app.AlertDialog.Builder(getContext())
                            .setTitle("Put the controls back?")
                            .setMessage("Every control returns to its default place and size, in portrait and landscape.")
                            .setPositiveButton("Put them back", (d, w) -> resetControlsNow())
                            .setNegativeButton("Cancel", null).show();
                    return true;
                }
                if (modeRect.contains(x, y)) {                                  // one thumb (the d-pad) or two thumbs (the split keys)
                    boolean on = !twoThumb;
                    Settings.setTwoThumb(getContext(), on);
                    setTwoThumb(on);
                    android.widget.Toast.makeText(getContext(), on ? "Two-thumb movement: left thumb forward and back, right thumb turns"
                            : "One-thumb movement: the d-pad", android.widget.Toast.LENGTH_SHORT).show();
                    return true;
                }
                for (int g = Settings.CONTROL_GROUPS - 1; g >= 0 && grabbed < 0; g--) {   // later groups sit on top
                    if (!groupActive(g)) {
                        continue;
                    }
                    RectF b = groupBounds(g);
                    b.inset(-dp(8), -dp(8));
                    if (b.contains(x, y)) {
                        grabbed = g;
                    }
                }
                if (grabbed >= 0) {
                    grabX = x;
                    grabY = y;
                    grabStart[0] = offset[grabbed][0];
                    grabStart[1] = offset[grabbed][1];
                }
                invalidate();
                break;
            }
            case MotionEvent.ACTION_POINTER_DOWN:
                if (grabbed >= 0 && pinchPointer < 0) {
                    int first = e.findPointerIndex(grabPointer), second = e.getActionIndex();
                    if (first >= 0 && first != second) {
                        pinchPointer = e.getPointerId(second);
                        pinchStartDist = (float) Math.hypot(e.getX(first) - e.getX(second), e.getY(first) - e.getY(second));
                        pinchStartScale = scale[grabbed];
                    }
                }
                break;
            case MotionEvent.ACTION_MOVE: {
                int at = grabbed >= 0 ? e.findPointerIndex(grabPointer) : -1;
                if (at >= 0 && getWidth() > 0 && getHeight() > 0) {
                    offset[grabbed][0] = grabStart[0] + (e.getX(at) - grabX) / getWidth();
                    offset[grabbed][1] = grabStart[1] + (e.getY(at) - grabY) / getHeight();
                    int other = pinchPointer >= 0 ? e.findPointerIndex(pinchPointer) : -1;
                    if (other >= 0 && pinchStartDist > dp(20)) {
                        float d = (float) Math.hypot(e.getX(at) - e.getX(other), e.getY(at) - e.getY(other));
                        scale[grabbed] = Math.max(0.5f, Math.min(2f, pinchStartScale * d / pinchStartDist));
                    }
                    layoutControls(getWidth(), getHeight());                  // clamps what was asked to the free area
                    invalidate();
                }
                break;
            }
            case MotionEvent.ACTION_POINTER_UP: {
                int id = e.getPointerId(e.getActionIndex());
                if (grabbed >= 0 && id == pinchPointer) {
                    pinchPointer = -1;                                        // the resizing finger let go: keep the size
                    saveGrabbed();
                } else if (grabbed >= 0 && id == grabPointer) {
                    if (pinchPointer >= 0) {                                  // hand the control over to the other finger
                        saveGrabbed();
                        grabPointer = pinchPointer;
                        pinchPointer = -1;
                        int now = e.findPointerIndex(grabPointer);
                        if (now >= 0) {
                            grabX = e.getX(now);
                            grabY = e.getY(now);
                            grabStart[0] = offset[grabbed][0];
                            grabStart[1] = offset[grabbed][1];
                        }
                    } else {
                        dropGrabbed();
                    }
                }
                break;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                dropGrabbed();
                break;
            default:
                break;
        }
        return true;
    }

    private void saveGrabbed() {
        if (grabbed >= 0) {
            Settings.setControlOffset(getContext(), offsetLandscape, offsetTwoThumb, grabbed, offset[grabbed][0], offset[grabbed][1]);
            Settings.setControlScale(getContext(), offsetLandscape, offsetTwoThumb, grabbed, scale[grabbed]);
        }
    }

    private void dropGrabbed() {
        saveGrabbed();
        grabbed = -1;
        grabPointer = -1;
        pinchPointer = -1;
        invalidate();
    }

    /** Every control back to its default place and size (the player's choices are forgotten, in both orientations). */
    private void resetControlsNow() {
        Settings.resetControls(getContext());
        java.util.Arrays.fill(scale, 1f);
        for (float[] o : offset) {
            o[0] = 0f;
            o[1] = 0f;
        }
        offsetsLoaded = false;
        layoutControls(getWidth(), getHeight());
        android.widget.Toast.makeText(getContext(), "Controls back to the default", android.widget.Toast.LENGTH_SHORT).show();
        invalidate();
    }

    /** The "put the controls back" button, drawn over the top of the game picture while the controls are being arranged. */
    /** White text centered in a button, made smaller until it fits. */
    private void drawFitted(Canvas c, String s, RectF r) {
        float size = dp(15);
        text.setTextSize(size);
        while (text.measureText(s) > r.width() - dp(16) && size > dp(9)) {
            size -= 1f;
            text.setTextSize(size);
        }
        text.setColor(Color.WHITE);
        c.drawText(s, r.centerX(), r.centerY() + size / 3f, text);
        text.setTextSize(dp(15));
    }

    private void updateResetRect() {
        float w = Math.min(Math.min(getWidth() * 0.8f, dp(300)), Math.max(dp(160), dst.width() - dp(8))), h = dp(44);   // (sideways, the picture is narrow: stay over it)
        float cx = (dst.left + dst.right) / 2f;
        float top = dst.top + dp(10);
        resetRect.set(cx - w / 2f, top, cx + w / 2f, top + h);
        modeRect.set(cx - w / 2f, top + h + dp(8), cx + w / 2f, top + 2 * h + dp(8));
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    /** Re-reads the saved positions (after Options reset them) and lays out again. */
    public void reloadControlOffsets() {
        offsetsLoaded = false;
        layoutControls(getWidth(), getHeight());
        invalidate();
    }

    private void layoutBase(int w, int h) {
        if (w > h) {
            layoutLandscape(w, h);
            return;
        }
        float left = insetLeft, right = w - insetRight, width = right - left;
        float top = insetTop, bottom = h - insetBottom, free = bottom - top;
        float gh = Math.min(width * (float) H / W, free * 0.60f);      // as large as the width allows, at most 60%
        if (pictureScale != Settings.FIT) {                            // a whole number of screen pixels per game pixel
            int most = Math.max(1, (int) Math.floor(gh / H));          // the largest that fits
            gh = H * (pictureScale == Settings.LARGEST ? most : Math.min(pictureScale, most));
        }
        float gw = gh * W / H;
        float gx = left + (width - gw) / 2f;
        dst.set(gx, top + free * 0.01f, gx + gw, top + free * 0.01f + gh);

        float softTop = dst.bottom + free * 0.012f;
        float soft = free * 0.055f;
        float third = width / 3f;
        float pad = width * 0.02f;
        buttons.get(0).r.set(left + pad, softTop, left + third - pad, softTop + soft);                // SOFT1
        buttons.get(1).r.set(left + third + pad, softTop, left + 2 * third - pad, softTop + soft);    // CLR
        buttons.get(2).r.set(left + 2 * third + pad, softTop, right - pad, softTop + soft);           // SOFT2

        // the status line sits at the bottom of the free area; the pad and buttons end above it, a little higher
        // than the bare edge, so a thumb resting on them never touches the gesture area
        statusY = bottom - free * 0.008f;
        float areaTop = softTop + soft + free * 0.012f;
        float areaBottom = bottom - free * 0.04f;
        float area = areaBottom - areaTop;
        float cy = areaTop + area / 2f;
        colL0 = left;
        colL1 = left + width / 2f;
        colR0 = left + width / 2f;
        colR1 = right;
        areaT = areaTop;
        areaB = areaBottom;
        padR = Math.min(width * 0.24f, area * 0.46f);
        padX = left + width * 0.27f;
        padY = cy;
        float big = Math.min(width * 0.13f, area * 0.27f);
        placeButtons(left + width * 0.75f, cy + area * 0.16f, big,              // Action
                left + width * 0.61f, cy - area * 0.21f,                        // Magic
                left + width * 0.89f, cy - area * 0.27f);                       // Status
    }

    /**
     * Action is the big round button; Magic and Status are the smaller ones up and to each side of it, at the positions given
     * (the angles and sizes the layout was designed with). Each of the two is then slid along the line to Action's centre
     * until the circles just touch, so the three read as one group.
     */
    private void placeButtons(float ax, float ay, float big, float mx, float my, float sx, float sy) {
        float small = big * 0.72f;
        float action = big * 1.15f;                                            // Action is the one that is pressed most: a bit bigger
        setCircle(buttons.get(3), ax, ay, action);                             // Action
        float[] magic = towards(ax, ay, mx, my, action + small);
        float[] status = towards(ax, ay, sx, sy, action + small);
        setCircle(buttons.get(4), magic[0], magic[1], small);                  // Magic
        setCircle(buttons.get(5), status[0], status[1], small);                // Status
    }

    /** The point on the line from (ax, ay) through (x, y) that is `distance` from (ax, ay). */
    private static float[] towards(float ax, float ay, float x, float y, float distance) {
        float dx = x - ax, dy = y - ay;
        float length = (float) Math.hypot(dx, dy);
        if (length < 1f) {
            return new float[]{x, y};
        }
        return new float[]{ax + dx / length * distance, ay + dy / length * distance};
    }

    private static void setCircle(Button b, float cx, float cy, float r) {
        b.r.set(cx - r, cy - r, cx + r, cy + r);
    }

    @Override
    protected void onDraw(Canvas c) {
        c.drawColor(Color.BLACK);
        boolean flipping = isFlipActive();
        if (flipping && flip != null) {
            flip.drawBody(c);
        }
        epxPending = false;
        List<TextItem> shown;
        synchronized (frame) {
            shown = items;                                       // the strings that belong to the picture drawn here
            if (hasFrame) {
                drawPicture(c);
            }
        }
        if (epxPending) {
            finishScale2x(c);
        }
        drawSharpText(c, dst, shown);
        if (flipping && flip != null) {
            flip.drawKeys(c, allDown());
            text.setTextSize(getHeight() * 0.012f);
            text.setColor(0xFF8EA4BF);
            c.drawText(status, getWidth() / 2f, statusY, text);
            text.setColor(Color.WHITE);
            return;
        }
        // the direction pad and the buttons (a controller's presses light them too)
        Set<String> down = allDown();
        if (twoThumb) {
            skin.drawKey(c, upR, 0, down.contains("UP"));
            skin.drawKey(c, downR, 180, down.contains("DOWN"));
            skin.drawKey(c, leftR, 270, down.contains("LEFT"));
            skin.drawKey(c, rightR, 90, down.contains("RIGHT"));
        } else {
            skin.drawPad(c, padX, padY, padR, down);
        }
        for (Button b : buttons) {
            boolean on = down.contains(b.key);
            if (b.round) {
                skin.drawBall(c, b.r, b.label, b.key.equals("SELECT") ? actionWord() : null, b.key.equals("SELECT") ? ControlSkin.BLUE
                        : b.key.equals("STAR") ? ControlSkin.VIOLET : ControlSkin.GOLD, on);
            } else {
                String word = b.key.equals("SOFT1") ? softkeyWord(true) : b.key.equals("SOFT2") ? softkeyWord(false) : null;
                skin.drawPill(c, b.r, b.label, word, on);
            }
        }
        if (editing) {
            outline.setStyle(Paint.Style.STROKE);
            outline.setStrokeWidth(dp(2));
            if (dashes == null) {
                dashes = new android.graphics.DashPathEffect(new float[]{dp(8), dp(6)}, 0);
            }
            outline.setPathEffect(dashes);
            for (int g = 0; g < Settings.CONTROL_GROUPS; g++) {
                if (!groupActive(g)) {
                    continue;
                }
                outline.setColor(g == grabbed ? 0xFFFFD54F : 0xFFE6EEFB);
                RectF b = groupBounds(g);
                b.inset(-dp(6), -dp(6));
                c.drawRoundRect(b, dp(12), dp(12), outline);
            }
            updateResetRect();
            fill.setStyle(Paint.Style.FILL);
            fill.setColor(0xFF1C5FD1);
            c.drawRoundRect(resetRect, dp(10), dp(10), fill);
            text.setTextSize(dp(15));
            text.setColor(Color.WHITE);
            drawFitted(c, "Put the controls back", resetRect);
            fill.setColor(0xFF2B4A7A);
            c.drawRoundRect(modeRect, dp(10), dp(10), fill);
            text.setColor(Color.WHITE);
            drawFitted(c, twoThumb ? "Movement: two thumbs (tap for one)" : "Movement: one thumb (tap for two)", modeRect);
            String hint = "Drag to move, pinch to resize. Back when done.";
            float size = Math.max(getHeight() * 0.018f, dp(13));
            text.setTextSize(size);
            while (text.measureText(hint) > getWidth() * 0.92f && size > dp(9)) {      // shrink until it fits the width
                size -= 1f;
                text.setTextSize(size);
            }
            text.setColor(0xFFFFD54F);
            c.drawText(hint, getWidth() / 2f, statusY - dp(6), text);
            text.setColor(Color.WHITE);
            return;
        }
        text.setTextSize(getHeight() * 0.014f);
        text.setColor(0xFF8EA4BF);
        c.drawText(status, dst.centerX(), statusY, text);
        text.setColor(Color.WHITE);
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (editing) {
            return onEditTouch(e);
        }
        int action = e.getActionMasked();
        if (needDown) {
            if (action != MotionEvent.ACTION_DOWN) {
                return true;                                               // still the finger from editing
            }
            needDown = false;
        }
        trackTap(e, action);
        Set<String> now = new HashSet<>();
        if (action != MotionEvent.ACTION_UP && action != MotionEvent.ACTION_CANCEL) {
            int skip = action == MotionEvent.ACTION_POINTER_UP ? e.getActionIndex() : -1;
            for (int i = 0; i < e.getPointerCount(); i++) {
                if (i != skip) {
                    keysAt(e.getX(i), e.getY(i), now);
                }
            }
        }
        for (String k : new ArrayList<>(held)) {
            if (!now.contains(k)) {
                held.remove(k);
                if (!padHeld.containsKey(k)) {                     // (a controller may still be holding it)
                    send(k, false);
                }
            }
        }
        for (String k : now) {
            if (held.add(k)) {
                send(k, true);
            }
        }
        invalidate();
        return true;
    }

    /** A short touch on the picture that does not move is a tap on whatever the game drew there. */
    private void trackTap(MotionEvent e, int action) {
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex();
            if (tapPointer == -1 && dst.contains(e.getX(i), e.getY(i))) {
                tapPointer = e.getPointerId(i);
                tapX = e.getX(i);
                tapY = e.getY(i);
                tapTime = e.getEventTime();
            }
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
            int i = e.getActionIndex();
            if (tapPointer != -1 && e.getPointerId(i) == tapPointer) {
                float x = e.getX(i), y = e.getY(i);
                boolean still = Math.hypot(x - tapX, y - tapY) <= slop * 2;
                if (still && e.getEventTime() - tapTime < 500 && tapSink != null && dst.contains(x, y)) {
                    tapSink.tap((x - dst.left) / dst.width() * W, (y - dst.top) / dst.height() * H);
                }
                tapPointer = -1;
            }
        } else if (action == MotionEvent.ACTION_CANCEL) {
            tapPointer = -1;
        }
    }

    // keys held from a controller: the sources (GamePad.FROM_*) that hold each one, so the stick and the D-pad can share a key
    private final java.util.Map<String, Integer> padHeld = new java.util.HashMap<>();

    /** A controller button or stick direction went down or up: presses the phone key unless the controls are being moved. */
    public void padKey(String name, boolean down, int source) {
        if (editing) {
            return;
        }
        int before = padHeld.containsKey(name) ? padHeld.get(name) : 0;
        int after = down ? (before | source) : (before & ~source);
        if (after == 0) {
            padHeld.remove(name);
        } else {
            padHeld.put(name, after);
        }
        if (before == 0 && after != 0 && !held.contains(name)) {
            send(name, true);
        } else if (before != 0 && after == 0 && !held.contains(name)) {      // (a finger may still be holding it)
            send(name, false);
        }
    }

    /** Lets go of every key a controller holds (a menu or another screen took the controller's focus). */
    public void releasePad() {
        for (String k : new ArrayList<>(padHeld.keySet())) {
            if (!held.contains(k)) {
                send(k, false);
            }
        }
        padHeld.clear();
    }

    /** Lets go of every key (the app left the foreground). */
    public void releaseAll() {
        if (editing) {
            dropGrabbed();                                     // the app is leaving in the middle of a drag: keep where it got to
        }
        for (String k : new ArrayList<>(held)) {
            send(k, false);
        }
        held.clear();
        for (String k : new ArrayList<>(padHeld.keySet())) {
            send(k, false);
        }
        padHeld.clear();
        tapPointer = -1;
        postInvalidate();
    }

    private void send(String key, boolean down) {
        if (sink != null) {
            sink.key(key, down);
        }
    }

    private static boolean inKey(RectF r, float x, float y, float slack) {
        return x >= r.left - slack && x <= r.right + slack && y >= r.top - slack && y <= r.bottom + slack;
    }

    private void keysAt(float x, float y, Set<String> out) {
        if (isFlipActive() && flip != null) {
            flip.keysAt(x, y, out);
            return;
        }
        for (Button b : buttons) {
            RectF r = b.r;
            if (b.round) {                                                  // a circle, with a little slack for a thumb
                float radius = r.width() / 2f * 1.04f;
                if (Math.hypot(x - r.centerX(), y - r.centerY()) <= radius) {
                    out.add(b.key);
                }
            } else if (r.contains(x, y)) {
                out.add(b.key);
            }
        }
        if (twoThumb) {                                                     // four separate keys, no diagonals to aim for
            float slack = dp(2);                                            // (small: neighboring keys are only a few dp apart)
            if (inKey(upR, x, y, slack)) {
                out.add("UP");
            }
            if (inKey(downR, x, y, slack)) {
                out.add("DOWN");
            }
            if (inKey(leftR, x, y, slack)) {
                out.add("LEFT");
            }
            if (inKey(rightR, x, y, slack)) {
                out.add("RIGHT");
            }
            return;
        }
        float dx = x - padX, dy = y - padY;
        if (dx * dx + dy * dy <= padR * padR * 1.4f && dx * dx + dy * dy >= padR * padR * 0.02f) {
            float t = padR * 0.3f;
            if (dx < -t) out.add("LEFT");
            if (dx > t) out.add("RIGHT");
            if (dy < -t) out.add("UP");
            if (dy > t) out.add("DOWN");
        }
    }
}
