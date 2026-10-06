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
 */
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
