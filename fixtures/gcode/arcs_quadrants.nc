; arcs in every quadrant, oblique arcs, I-only, J-only and zero-radius arcs
G90
M3 S500
G1 F600
G0 X1 Y0
G3 X0 Y1 I-1 J0
G3 X-1 Y0 I0 J-1
G3 X0 Y-1 I1 J0
G3 X1 Y0 I0 J1
G0 X1 Y1
G3 X-1 Y1 I-1 J-1
G3 X-1 Y-1 I1 J-1
G0 X20 Y0
G2 X30 Y0 I5
G2 X30 Y10 J5
G2 X40 Y10 I0 J0
G2 X40 Y10 R7
M5
