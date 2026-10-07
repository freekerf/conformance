; rust_divergence: DIV-053
; an absurd move overflows the time estimate: LaserGRBL stops analyzing the file there
G0 X1 Y1
X99999999999999999999
G0 X5 Y5
M3 S100
G1 X10 F100
M5
