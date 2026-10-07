; feeds: G1 without F takes no time, F above the max rate is capped, ms rounding
G1 X100
G1 X200 F60000
G0 X0
G1 X1 F7
G1 Y1 F7
G91
G1 X0.001 F1
G90
G4 P0.0005
