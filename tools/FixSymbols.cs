// Drops debug sequence points that mcs places on an instruction preceded by an IL
// prefix (constrained./volatile./readonly./unaligned./tail.). AltCover inserts its
// visit call at every sequence point, and inserting between a prefix and the
// instruction it modifies produces invalid IL ("constrained call ... is not
// assignable"). The IL itself is not changed; only the .mdb line table of the copy.
//
// Usage: mono FixSymbols.exe <in.exe> <out.exe>   (reads/writes <exe>.mdb)
using System;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;
using Mono.Cecil.Mdb;

static class FixSymbols
{
	static int Main(string[] args)
	{
		var rp = new ReaderParameters { ReadSymbols = true, SymbolReaderProvider = new MdbReaderProvider(), InMemory = true };
		int dropped = 0;
		using (var module = ModuleDefinition.ReadModule(args[0], rp))
		{
			foreach (var type in module.GetTypes())
				foreach (var method in type.Methods.Where(m => m.HasBody && m.DebugInformation.HasSequencePoints))
				{
					var byOffset = method.Body.Instructions.ToDictionary(i => i.Offset);
					var sps = method.DebugInformation.SequencePoints;
					for (int k = sps.Count - 1; k >= 0; k--)
					{
						Instruction ins;
						if (byOffset.TryGetValue(sps[k].Offset, out ins) && ins.Previous != null && ins.Previous.OpCode.OpCodeType == OpCodeType.Prefix)
						{
							sps.RemoveAt(k);
							dropped++;
						}
					}
				}
			module.Write(args[1], new WriterParameters { WriteSymbols = true, SymbolWriterProvider = new MdbWriterProvider() });
		}
		Console.WriteLine("dropped {0} sequence points after IL prefixes", dropped);
		return 0;
	}
}
