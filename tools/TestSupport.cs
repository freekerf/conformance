// Test-side helpers compiled against the LaserGRBL.exe under test (never shipped).
//
// Why C#: under pythonnet + Mono 6.8, Python code running on a CLR-created thread
// (e.g. a Python IComWrapper called by GrblCore's RX/TX threads, or a Python event
// handler) deadlocks against Python->CLR calls from the main thread. So everything
// the core's own threads touch is plain C#; Python only calls *into* these objects.
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;

namespace LaserGRBLTests
{
	// In-memory IComWrapper. The host (GrblCore) writes bytes and reads lines; the
	// test-side device takes the written bytes (TakeTx) and feeds lines back (FeedHost).
	public class LoopbackCom : LaserGRBL.ComWrapper.IComWrapper
	{
		private readonly object sync = new object();
		private readonly Queue<string> rx = new Queue<string>();
		private readonly StringBuilder partial = new StringBuilder();
		private readonly List<byte> tx = new List<byte>();
		private bool opened;
		private int connectEvents;

		public object[] ConfigureArgs;
		public int OpenCount;
		public readonly List<bool> CloseLog = new List<bool>();
		public Exception FailOpen;      // thrown by the next Open()
		public Exception ReadError;     // thrown (once) by the next ReadLineBlocking()
		public Exception HasDataError;  // thrown (once) by the next HasData()
		public Exception WriteError;    // thrown (once) by the next Write()
		public bool ReturnNullOnce;     // next ReadLineBlocking() returns null once

		public void Configure(params object[] param) { ConfigureArgs = param; }

		public void Open()
		{
			if (FailOpen != null) throw FailOpen;
			lock (sync) { opened = true; OpenCount++; connectEvents++; Monitor.PulseAll(sync); }
		}

		public void Close(bool auto)
		{
			lock (sync) { opened = false; CloseLog.Add(auto); Monitor.PulseAll(sync); }
		}

		public bool IsOpen { get { lock (sync) return opened; } }

		// lets stepped tests mark the port open without a device connect event
		public void ForceOpen(bool value) { lock (sync) { opened = value; Monitor.PulseAll(sync); } }

		public void Write(byte b) { Push(new byte[] { b }); }
		public void Write(byte[] arr) { Push(arr); }
		public void Write(string text) { Push(Encoding.UTF8.GetBytes(text)); }

		private void Push(byte[] data)
		{
			lock (sync)
			{
				if (WriteError != null) { Exception e = WriteError; WriteError = null; throw e; }
				tx.AddRange(data);
				Monitor.PulseAll(sync);
			}
		}

		public string ReadLineBlocking()
		{
			lock (sync)
			{
				if (ReturnNullOnce) { ReturnNullOnce = false; return null; }
				while (opened && rx.Count == 0 && ReadError == null)
					Monitor.Wait(sync, 20);
				if (ReadError != null) { Exception e = ReadError; ReadError = null; throw e; }
				return rx.Count > 0 ? rx.Dequeue() : null;
			}
		}

		public bool HasData()
		{
			lock (sync)
			{
				if (HasDataError != null) { Exception e = HasDataError; HasDataError = null; throw e; }
				return rx.Count > 0;
			}
		}

		// ---- device side ----
		public byte[] TakeTx(int timeoutMs)
		{
			lock (sync)
			{
				if (tx.Count == 0 && timeoutMs > 0) Monitor.Wait(sync, timeoutMs);
				byte[] rv = tx.ToArray();
				tx.Clear();
				return rv;
			}
		}

		public int TakeConnectEvents()
		{
			lock (sync) { int n = connectEvents; connectEvents = 0; return n; }
		}

		public void FeedHost(string data)
		{
			lock (sync)
			{
				foreach (char c in data)
				{
					if (c == '\n') { rx.Enqueue(partial.ToString()); partial.Length = 0; }
					else partial.Append(c);
				}
				Monitor.PulseAll(sync);
			}
		}

		public string TakeHostLine()
		{
			lock (sync) return rx.Count > 0 ? rx.Dequeue() : null;
		}

		public int HostLinesPending { get { lock (sync) return rx.Count; } }
	}

	// Records GrblCore events from whatever thread raises them.
	public class EventRecorder
	{
		private readonly List<string> events = new List<string>();
		private readonly LaserGRBL.GrblCore core;

		public EventRecorder(LaserGRBL.GrblCore core)
		{
			this.core = core;
			core.MachineStatusChanged += () => Add("status:" + core.MachineStatus);
			core.IssueDetected += (issue) => Add("issue:" + issue);
			core.OnOverrideChange += () => Add("override");
			core.JogStateChange += (jog) => Add("jog:" + jog);
			core.OnLoopCountChange += (v) => Add("loop:" + v.ToString(System.Globalization.CultureInfo.InvariantCulture));
			core.OnProgramEnded += () => Add("ended");
			core.OnFileLoading += (e, f) => Add("loading:" + f);
			core.OnFileLoaded += (e, f) => Add("loaded:" + f);
			core.OnAutoSizeDrawing += (c) => Add("autosize");
			core.OnZoomInDrawing += (c) => Add("zoomin");
			core.OnZoomOutDrawing += (c) => Add("zoomout");
		}

		private void Add(string e) { lock (events) events.Add(e); }

		public string[] Snapshot() { lock (events) return events.ToArray(); }

		public void Clear() { lock (events) events.Clear(); }
	}

	// Subscribes only to GrblCore.OnFileLoading (not OnFileLoaded).
	public class FileLoadingProbe
	{
		public int Count;
		public FileLoadingProbe(LaserGRBL.GrblCore core) { core.OnFileLoading += (e, f) => Count++; }
	}

	// Counts GrblFile.OnFileLoading / OnFileLoaded (raised on the file's loading thread).
	public class GrblFileEvents
	{
		public int Loading, Loaded;
		public GrblFileEvents(LaserGRBL.GrblFile file)
		{
			file.OnFileLoading += (e, f) => System.Threading.Interlocked.Increment(ref Loading);
			file.OnFileLoaded += (e, f) => System.Threading.Interlocked.Increment(ref Loaded);
		}
	}

	// Subscribes to the static Grblv11Emulator.EmulatorMessage event (raised on the
	// emulator's own threads) and records the messages.
	public static class EmulatorProbe
	{
		private static readonly List<string> messages = new List<string>();
		private static bool attached;
		public static bool Throw;

		public static void Attach()
		{
			if (attached) return;
			attached = true;
			LaserGRBL.GrblEmulator.Grblv11Emulator.EmulatorMessage += OnMessage;
		}

		public static void Detach()
		{
			if (!attached) return;
			attached = false;
			LaserGRBL.GrblEmulator.Grblv11Emulator.EmulatorMessage -= OnMessage;
		}

		private static void OnMessage(string m)
		{
			lock (messages) messages.Add(m);
			if (Throw) throw new InvalidOperationException("probe");
		}

		public static string[] Snapshot() { lock (messages) return messages.ToArray(); }
		public static void Clear() { lock (messages) messages.Clear(); }
	}

	// Collects what a Grblv11Emulator sends (stands in for ComWrapper.Emulator.SendData).
	public class EmulatorSink
	{
		private readonly List<string> lines = new List<string>();
		public bool Throw;
		public int Thrown;
		public void Send(string message)
		{
			if (Throw) { Thrown++; throw new InvalidOperationException("sink"); }
			lock (lines) lines.Add(message);
		}
		public LaserGRBL.GrblEmulator.Grblv11Emulator.SendMessage Delegate { get { return Send; } }
		public string[] Snapshot() { lock (lines) return lines.ToArray(); }
	}

	public static class Helpers
	{
		// Snapshot of the core's command log taken under the core's own lock, so it is
		// safe while the RX/TX threads are running.
		public static string[] SentTexts(LaserGRBL.GrblCore core)
		{
			lock (core)
			{
				List<LaserGRBL.IGrblRow> rows = core.SentCommand(0, int.MaxValue);
				string[] rv = new string[rows.Count];
				for (int i = 0; i < rv.Length; i++) rv[i] = rows[i].GetDecodedMessage();
				return rv;
			}
		}

		// Pure-CLR CPU workload, used by the harness self-test for thread safety.
		public static int ParseMany(int n)
		{
			int moves = 0;
			for (int i = 0; i < n; i++)
			{
				LaserGRBL.GrblCommand c = new LaserGRBL.GrblCommand("G1 X" + (i % 10) + " Y2");
				c.BuildHelper();
				if (c.IsMovement) moves++;
			}
			return moves;
		}

		public static Thread StartParseThread(int n)
		{
			Thread t = new Thread(() => ParseMany(n));
			t.Start();
			return t;
		}
	}
}
