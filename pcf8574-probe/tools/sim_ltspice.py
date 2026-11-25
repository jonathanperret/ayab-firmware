"""Write the fitted slow model as an LTspice schematic.

usage: sim_ltspice.py            (run from the probe folder, after sim_fit.py)
Reads sim/fit.json (the "two inductances" result) and writes sim/coil_driver.asc, the same circuit as
sim/coil_driver.cir: one coil and its driver channel, run for the two on-times the model was fitted
to. Open the .asc in LTspice and press Run; plot V(out) and I(L1)."""
import os, json

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = json.load(open(os.path.join(HERE, "sim", "fit.json")))["two inductances"]


def eng(v):
    """A number in the short form LTspice shows nicely (e.g. 143m, 91.2, 7.9e-10)."""
    return "%.4g" % v


ASC = """Version 4
SHEET 1 1240 620
WIRE 0 16 0 112
WIRE 416 16 0 16
WIRE 848 16 480 16
WIRE 848 112 848 16
WIRE 112 112 0 112
WIRE 288 112 192 112
WIRE 464 112 368 112
WIRE 592 112 544 112
WIRE 640 112 592 112
WIRE 768 112 720 112
WIRE 848 112 768 112
WIRE 592 192 592 112
WIRE 640 192 592 192
WIRE 768 192 720 192
WIRE 768 192 768 112
WIRE 848 144 848 112
WIRE 992 208 896 208
WIRE 848 240 848 224
WIRE 848 336 848 320
FLAG 0 192 0
FLAG 848 416 0
FLAG 896 160 0
FLAG 992 288 0
FLAG 0 112 sup
FLAG 848 112 out
SYMBOL voltage 0 96 R0
SYMATTR InstName Vsup
SYMATTR Value {{VS}}
SYMBOL res 208 96 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName Rwire
SYMATTR Value {{RW*n_coils}}
SYMBOL res 384 96 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName Rcoil
SYMATTR Value {{R}}
SYMBOL ind 448 128 R270
WINDOW 0 32 56 VTop 2
WINDOW 3 5 56 VBottom 2
SYMATTR InstName L1
SYMATTR Value {{L1}}
SYMATTR SpiceLine Rser=0
SYMBOL ind 624 128 R270
WINDOW 0 32 56 VTop 2
WINDOW 3 5 56 VBottom 2
SYMATTR InstName L2
SYMATTR Value {{L2}}
SYMATTR SpiceLine Rser=0
SYMBOL res 736 176 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName Riron
SYMATTR Value {{RI}}
SYMBOL diode 480 0 R90
WINDOW 0 0 32 VBottom 2
WINDOW 3 32 32 VTop 2
SYMATTR InstName Dclamp
SYMATTR Value DCLAMP
SYMBOL sw 848 128 M0
SYMATTR InstName S1
SYMATTR Value SWDRV
SYMBOL voltage 848 224 R0
SYMATTR InstName Vdrop
SYMATTR Value {{V0}}
SYMBOL res 832 320 R0
SYMATTR InstName Ron
SYMATTR Value {{RON}}
SYMBOL voltage 992 192 R0
SYMATTR InstName Vctl
SYMATTR Value PULSE(0 1 1m 1u 1u {{t_on}} 1)
TEXT 0 -192 Left 2 ;One solenoid coil of the AYAB interface board and its driver channel: slow model.
TEXT 0 -160 Left 2 ;Fitted to scope captures of the driver output (journal entries 177-179, 204).
TEXT 0 -128 Left 2 ;Nothing faster than about 20 us is modelled: no capacitances, no diode recovery, no wiring inductance.
TEXT 0 -96 Left 2 ;Plot V(out), I(L1), I(Dclamp). The driver switches on at 1 ms and off t_on later. Coil current counts positive from the supply to the output.
TEXT 0 480 Left 2 !.param VS={VS} RW={RW} R={R} n_coils=6
TEXT 0 512 Left 2 !.param L1={L1} L2={L2} RI={RI}
TEXT 0 544 Left 2 !.param V0={V0} RON={RON}
TEXT 0 576 Left 2 !.model DCLAMP D(Is={IS} N={N} Rs={RS})
TEXT 560 480 Left 2 !.model SWDRV SW(Ron=0.01 Roff=1G Vt=0.5 Vh=0)
TEXT 560 512 Left 2 !.step param t_on list 5.26m 0.34m
TEXT 560 544 Left 2 !.tran 0 13m 0 2u
TEXT 96 160 Left 1 ;shared supply wiring, per coil on
TEXT 288 160 Left 1 ;coil resistance (measured)
TEXT 448 160 Left 1 ;inductance at first
TEXT 608 48 Left 1 ;extra inductance later
TEXT 608 224 Left 1 ;stands for the iron
TEXT 496 -16 Left 1 ;clamp diode back to the supply
TEXT 1040 240 Left 1 ;on at 1 ms, off t_on later
TEXT 912 280 Left 1 ;driver's fixed drop
TEXT 912 376 Left 1 ;driver's resistance
""".format(VS=eng(F["VS"]), RW=eng(F["RW"]), R=eng(F["R"]), L1=eng(F["L1"]), L2=eng(F["L2"]), RI=eng(F["RI"]), V0=eng(F["V0"]), RON=eng(F["RON"]), IS=eng(F["IS"]), N=eng(F["N"]), RS=eng(F["RS"]))
path = os.path.join(HERE, "sim", "coil_driver.asc")
open(path, "w").write(ASC)
print("wrote", path)
