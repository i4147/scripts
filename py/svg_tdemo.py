from svg_turtle import SvgTurtle

t = SvgTurtle(500, 500)
t.forward(200)
t.dot(20)
t.save_as("/sdcard/example.svg")
