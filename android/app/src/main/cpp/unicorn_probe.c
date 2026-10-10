/* Spike 1, step 1: load Unicorn inside an app and run ARM code (checks executable memory at target SDK 36).
 * The Unicorn API is used through dlopen/dlsym with the few declarations below (values from unicorn 2.1.4's
 * unicorn.h and arm.h), so the app build needs no Unicorn source. */
#include <android/log.h>
#include <dlfcn.h>
#include <jni.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "recast", __VA_ARGS__)

typedef struct uc_struct uc_engine;
typedef int (*uc_open_t)(unsigned arch, unsigned mode, uc_engine **uc);
typedef int (*uc_close_t)(uc_engine *uc);
typedef int (*uc_mem_map_t)(uc_engine *uc, uint64_t address, size_t size, uint32_t perms);
typedef int (*uc_mem_write_t)(uc_engine *uc, uint64_t address, const void *bytes, size_t size);
typedef int (*uc_reg_read_t)(uc_engine *uc, int regid, void *value);
typedef int (*uc_emu_start_t)(uc_engine *uc, uint64_t begin, uint64_t until, uint64_t timeout, size_t count);
typedef const char *(*uc_strerror_t)(int code);
typedef unsigned (*uc_version_t)(unsigned *major, unsigned *minor);

#define UC_ARCH_ARM 1
#define UC_MODE_ARM 0
#define UC_PROT_ALL 7
#define UC_ARM_REG_R0 66

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

/* The library handle is never closed (dlclose): this is a probe that runs once. */
JNIEXPORT jstring JNICALL
Java_com_khrecast_recast_BenchActivity_runUnicornProbe(JNIEnv *env, jclass cls) {
    char out[512];
    void *lib = dlopen("libunicorn.so", RTLD_NOW);
    if (!lib) {
        snprintf(out, sizeof out, "FAILED: dlopen libunicorn.so: %s", dlerror());
        LOG("%s", out);
        return (*env)->NewStringUTF(env, out);
    }
    uc_open_t uc_open = (uc_open_t)dlsym(lib, "uc_open");
    uc_close_t uc_close = (uc_close_t)dlsym(lib, "uc_close");
    uc_mem_map_t uc_mem_map = (uc_mem_map_t)dlsym(lib, "uc_mem_map");
    uc_mem_write_t uc_mem_write = (uc_mem_write_t)dlsym(lib, "uc_mem_write");
    uc_reg_read_t uc_reg_read = (uc_reg_read_t)dlsym(lib, "uc_reg_read");
    uc_emu_start_t uc_emu_start = (uc_emu_start_t)dlsym(lib, "uc_emu_start");
    uc_strerror_t uc_strerror = (uc_strerror_t)dlsym(lib, "uc_strerror");
    uc_version_t uc_version = (uc_version_t)dlsym(lib, "uc_version");
    if (!uc_open || !uc_close || !uc_mem_map || !uc_mem_write || !uc_reg_read || !uc_emu_start || !uc_strerror ||
        !uc_version) {
        snprintf(out, sizeof out, "FAILED: a Unicorn symbol is missing");
        LOG("%s", out);
        return (*env)->NewStringUTF(env, out);
    }
    unsigned major = 0, minor = 0;
    uc_version(&major, &minor);

    uc_engine *uc = NULL;
    int err = uc_open(UC_ARCH_ARM, UC_MODE_ARM, &uc);
    if (err) {
        snprintf(out, sizeof out, "FAILED: uc_open: %s", uc_strerror(err));
        LOG("%s", out);
        return (*env)->NewStringUTF(env, out);
    }
    /* mov r0,#6 ; mov r1,#7 ; mul r0,r0,r1  (ARM, little endian) */
    static const uint32_t code[] = {0xE3A00006, 0xE3A01007, 0xE0000190};
    const uint64_t base = 0x10000;
    err = uc_mem_map(uc, base, 0x10000, UC_PROT_ALL);
    if (!err) err = uc_mem_write(uc, base, code, sizeof code);
    if (!err) err = uc_emu_start(uc, base, base + sizeof code, 0, 0);
    uint32_t r0 = 0;
    if (!err) err = uc_reg_read(uc, UC_ARM_REG_R0, &r0);
    if (err) {
        snprintf(out, sizeof out, "FAILED: %s (unicorn %u.%u)", uc_strerror(err), major, minor);
        LOG("%s", out);
        uc_close(uc);
        return (*env)->NewStringUTF(env, out);
    }

    /* a longer run, to see the translator is working and how fast: a loop of 65,536 iterations (3 instructions each) */
    static const uint32_t loop[] = {
        0xE3A00000,  /* mov r0,#0          */
        0xE3A01801,  /* mov r1,#0x10000    (65536) */
        0xE2800001,  /* add r0,r0,#1       */
        0xE2511001,  /* subs r1,r1,#1      */
        0x1AFFFFFC,  /* bne  -> add        */
    };
    uint32_t n = 0;
    double ms = 0;
    err = uc_mem_write(uc, base + 0x100, loop, sizeof loop);
    if (!err) {
        double t0 = now_ms();
        err = uc_emu_start(uc, base + 0x100, base + 0x100 + sizeof loop, 0, 0);
        ms = now_ms() - t0;
    }
    if (!err) err = uc_reg_read(uc, UC_ARM_REG_R0, &n);
    uc_close(uc);
    if (err) {
        snprintf(out, sizeof out, "6*7 = %u OK, then FAILED the loop: %s", r0, uc_strerror(err));
    } else {
        snprintf(out, sizeof out, "Unicorn %u.%u loaded.\nARM 6 x 7 = %u (expected 42): %s\nLoop %u iterations in %.1f ms: %s",
                 major, minor, r0, r0 == 42 ? "PASS" : "FAIL", n, ms, n == 65536 ? "PASS" : "FAIL");
    }
    LOG("%s", out);
    return (*env)->NewStringUTF(env, out);
}
