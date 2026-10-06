/*
 * Native shims that let LaserGRBL's core run on Mono/Linux inside the test harness.
 * Routed in through the generated Mono global config (scripts/make_mono_config.py).
 *
 * 1. kernel32 timers used by Tools.HiResTimer (QueryPerformanceCounter/Frequency,
 *    GetTickCount). Win32 BOOL is a 4-byte int; the managed side marshals bool as BOOL.
 * 2. MonoPosixHelper!set_signal: Mono's SerialPort always sets DTR/RTS when opening a
 *    port. A pseudo terminal has no modem lines and the ioctl fails with ENOTTY, so
 *    the open fails. Here the ioctl is attempted and ENOTTY/EINVAL are ignored, which
 *    makes a PTY usable as a serial port (real serial ports behave as before).
 * 3. gdiplus!GdipCreateBitmapFromScan0 (every `new Bitmap(w, h)`): libgdiplus gives a
 *    new bitmap 0 dpi, Windows GDI+ the screen resolution (96). Code that copies the
 *    resolution of such a bitmap (ImageTransform.ResizeImage: SetResolution) throws
 *    InvalidParameter on libgdiplus. The bitmap is created by the real libgdiplus and
 *    then given 96 dpi, like on Windows.
 * 4. gdiplus!GdipImageRotateFlip: on libgdiplus a pure flip (RotateNoneFlipX = 4,
 *    RotateNoneFlipY = 6) does nothing on a bitmap that a Graphics was ever created
 *    for (every bitmap ImageTransform draws, and new Bitmap(Image)); rotations and
 *    rotation+flip work. The flips are done as two of those instead
 *    (FlipX = Rotate90FlipX + Rotate90, FlipY = Rotate90FlipX + Rotate270).
 */
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <time.h>

static int64_t now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int QueryPerformanceFrequency(int64_t *freq)
{
	*freq = 1000000000LL; /* ns resolution */
	return 1;
}

int QueryPerformanceCounter(int64_t *count)
{
	*count = now_ns();
	return 1;
}

uint32_t GetTickCount(void)
{
	return (uint32_t)(now_ns() / 1000000LL);
}

/* values of System.IO.Ports.SerialSignal (Mono) */
enum { SIG_NONE = 0, SIG_CD = 1, SIG_CTS = 2, SIG_DSR = 4, SIG_DTR = 8, SIG_RTS = 16 };

/* same contract as MonoPosixHelper's set_signal: returns 1 on success, -1 on error */
int lg_set_signal(int fd, int signal, int value)
{
	int bits;
	switch (signal) {
	case SIG_DTR: bits = TIOCM_DTR; break;
	case SIG_RTS: bits = TIOCM_RTS; break;
	default: return -1;
	}
	if (ioctl(fd, value ? TIOCMBIS : TIOCMBIC, &bits) == -1) {
		if (errno == ENOTTY || errno == EINVAL)
			return 1; /* pseudo terminal: no modem control lines */
		return -1;
	}
	return 1;
}

typedef int (*create_scan0_fn)(int, int, int, int, void *, void **);
typedef int (*set_resolution_fn)(void *, float, float);
typedef int (*rotate_flip_fn)(void *, int);

static void *gdiplus_sym(const char *name)
{
	static void *lib;
	if (!lib)
		lib = dlopen("libgdiplus.so.0", RTLD_NOW);
	return lib ? dlsym(lib, name) : NULL;
}

int lg_GdipCreateBitmapFromScan0(int width, int height, int stride, int format, void *scan0, void **bitmap)
{
	static create_scan0_fn create;
	static set_resolution_fn set_resolution;
	if (!create) {
		create = (create_scan0_fn)gdiplus_sym("GdipCreateBitmapFromScan0");
		set_resolution = (set_resolution_fn)gdiplus_sym("GdipBitmapSetResolution");
		if (!create)
			return 18; /* GdiplusNotInitialized */
	}
	int status = create(width, height, stride, format, scan0, bitmap);
	if (status == 0 && set_resolution)
		set_resolution(*bitmap, 96.0f, 96.0f);
	return status;
}

/* values of System.Drawing.RotateFlipType */
enum { ROTATE_90 = 1, ROTATE_270 = 3, FLIP_X = 4, ROTATE_90_FLIP_X = 5, FLIP_Y = 6 };

int lg_GdipImageRotateFlip(void *image, int type)
{
	static rotate_flip_fn rotate_flip;
	if (!rotate_flip && !(rotate_flip = (rotate_flip_fn)gdiplus_sym("GdipImageRotateFlip")))
		return 18;
	if (type != FLIP_X && type != FLIP_Y)
		return rotate_flip(image, type);
	int status = rotate_flip(image, ROTATE_90_FLIP_X);
	return status != 0 ? status : rotate_flip(image, type == FLIP_X ? ROTATE_90 : ROTATE_270);
}
