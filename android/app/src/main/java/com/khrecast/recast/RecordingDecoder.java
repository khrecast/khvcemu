package com.khrecast.recast;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * Reads a recording (FLAC, MP3, AAC/M4A, OGG, WAV, whatever Android's own codecs know) into mono 16-bit samples at the game's
 * rate, written to a file the Python core can read (the desktop uses ffmpeg for this; the phone has none). Called from the
 * Sound screen and, through `audio.FILE_DECODER`, by the core when a recording replaces a tune.
 */
public final class RecordingDecoder {   // public: the Python core calls decodedPath through Chaquopy
    private RecordingDecoder() {
    }

    /** The decoded (mono, 22,050 Hz) copy of a recording, made now if it is missing or older than the recording; its path. */
    public static String decodedPath(String path) throws IOException {
        synchronized (DECODE_LOCK) {                       // the Sound screen and the game may ask for the same file at once
            File src = new File(path);
            File pcm = new File(path + ".22050.pcm");
            if (!pcm.isFile() || pcm.lastModified() < src.lastModified()) {
                decodeToFile(path, 22050, pcm.getAbsolutePath());
            }
            return pcm.getAbsolutePath();
        }
    }

    private static final Object DECODE_LOCK = new Object();
    /** A recording longer than this is cut here (the longest tune is a few minutes; this keeps memory and time in bounds). */
    static final int MAX_SECONDS = 600;

    /** Decodes `path` to `out` (raw little-endian 16-bit mono at `rate`); returns the number of samples. Throws on a file it cannot read. */
    public static long decodeToFile(String path, int rate, String out) throws IOException {
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec codec = null;
        File tmp = new File(out + ".part");
        try {
            extractor.setDataSource(path);
            int track = -1;
            MediaFormat format = null;
            for (int i = 0; i < extractor.getTrackCount() && track < 0; i++) {
                MediaFormat f = extractor.getTrackFormat(i);
                String mime = f.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) {
                    track = i;
                    format = f;
                }
            }
            if (track < 0) {
                throw new IOException("there is no sound in that file");
            }
            extractor.selectTrack(track);
            codec = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
            codec.configure(format, null, null, 0);
            codec.start();

            int srcRate = format.containsKey(MediaFormat.KEY_SAMPLE_RATE) ? format.getInteger(MediaFormat.KEY_SAMPLE_RATE) : rate;
            int channels = format.containsKey(MediaFormat.KEY_CHANNEL_COUNT) ? format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) : 1;
            int encoding = AudioFormat.ENCODING_PCM_16BIT;
            Resampler resampler = new Resampler(srcRate, rate);
            long samples = 0;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inputDone = false, outputDone = false;
            int idle = 0;                                   // dequeues in a row that gave nothing once the input ended
            long maxSamples = (long) rate * MAX_SECONDS;
            try (OutputStream os = new BufferedOutputStream(new FileOutputStream(tmp), 1 << 16)) {
                byte[] chunk = new byte[1 << 16];
                int chunkLen = 0;
                while (!outputDone) {
                    if (!inputDone) {
                        int in = codec.dequeueInputBuffer(10_000);
                        if (in >= 0) {
                            ByteBuffer buf = codec.getInputBuffer(in);
                            int n = extractor.readSampleData(buf, 0);
                            if (n < 0) {
                                codec.queueInputBuffer(in, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                                inputDone = true;
                            } else {
                                codec.queueInputBuffer(in, 0, n, extractor.getSampleTime(), 0);
                                extractor.advance();
                            }
                        }
                    }
                    int outIndex = codec.dequeueOutputBuffer(info, 10_000);
                    if (outIndex == MediaCodec.INFO_TRY_AGAIN_LATER) {
                        if (inputDone && ++idle > 500) {            // about five seconds with nothing coming out: give up
                            throw new IOException("the decoder stopped answering");
                        }
                    } else {
                        idle = 0;
                    }
                    if (outIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        MediaFormat of = codec.getOutputFormat();
                        if (of.containsKey(MediaFormat.KEY_SAMPLE_RATE)) {
                            int r = of.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                            if (r != srcRate) {
                                srcRate = r;
                                resampler = new Resampler(srcRate, rate);
                            }
                        }
                        if (of.containsKey(MediaFormat.KEY_CHANNEL_COUNT)) {
                            channels = of.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                        }
                        encoding = of.containsKey(MediaFormat.KEY_PCM_ENCODING) ? of.getInteger(MediaFormat.KEY_PCM_ENCODING)
                                : AudioFormat.ENCODING_PCM_16BIT;
                    } else if (outIndex >= 0) {
                        ByteBuffer out16 = codec.getOutputBuffer(outIndex);
                        if (out16 != null && info.size > 0) {
                            out16.position(info.offset);
                            out16.limit(info.offset + info.size);
                            out16.order(ByteOrder.nativeOrder());
                            int bytesPer = encoding == AudioFormat.ENCODING_PCM_FLOAT ? 4 : 2;
                            int frames = info.size / (bytesPer * Math.max(1, channels));
                            for (int f = 0; f < frames; f++) {
                                float sum = 0;
                                for (int c = 0; c < channels; c++) {
                                    sum += bytesPer == 4 ? out16.getFloat() * 32768f : out16.getShort();
                                }
                                int produced = resampler.push(sum / channels);
                                for (int p = 0; p < produced; p++) {
                                    short s = (short) Math.max(-32768, Math.min(32767, Math.round(resampler.out[p])));
                                    chunk[chunkLen++] = (byte) s;
                                    chunk[chunkLen++] = (byte) (s >> 8);
                                    samples++;
                                    if (chunkLen == chunk.length) {
                                        os.write(chunk, 0, chunkLen);
                                        chunkLen = 0;
                                    }
                                }
                            }
                        }
                        codec.releaseOutputBuffer(outIndex, false);
                        if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0 || samples >= maxSamples) {
                            outputDone = true;
                        }
                    }
                }
                os.write(chunk, 0, chunkLen);
            }
            if (samples == 0) {
                throw new IOException("there is no sound in that file");
            }
            File dest = new File(out);
            if (dest.exists() && !dest.delete()) {
                throw new IOException("could not replace " + out);
            }
            if (!tmp.renameTo(dest)) {
                throw new IOException("could not write " + out);
            }
            return samples;
        } catch (IllegalStateException | IllegalArgumentException e) {
            throw new IOException("Android cannot read that file (" + e.getMessage() + ")");
        } finally {
            tmp.delete();
            if (codec != null) {
                try {
                    codec.stop();
                } catch (IllegalStateException ignored) {
                }
                codec.release();
            }
            extractor.release();
        }
    }

    /** Linear resampling, one sample at a time (good enough for a comparison and a game tune at 22,050 Hz). */
    private static final class Resampler {
        final float[] out = new float[8];
        private final double step;                 // input samples per output sample
        private double pos;                        // where the next output sample sits, counted from `prev`
        private float prev, lastRaw;
        private boolean first = true;

        Resampler(int from, int to) {
            step = (double) from / to;
        }

        int push(float raw) {
            float x = step > 1.2 ? (raw + lastRaw) * 0.5f : raw;      // a little smoothing before dropping samples (against hiss)
            lastRaw = raw;
            if (first) {
                prev = x;
                first = false;
                pos = 0;
            }
            int n = 0;
            while (pos < 1.0 && n < out.length) {
                out[n++] = (float) (prev + (x - prev) * pos);
                pos += step;
            }
            pos -= 1.0;
            prev = x;
            return n;
        }
    }
}
