"""Generate the geometric application icon for packaging."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
im = Image.new("RGBA", (256, 256), (0,0,0,0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((7,7,249,249), radius=52, fill="#153d60")
d.line([(47,181),(47,55)], fill="#aecfe2", width=7)
d.line([(47,181),(208,181)], fill="#aecfe2", width=7)
d.line([(55,174),(82,97),(119,79),(150,86),(174,112),(187,151)], fill="#74d1cf", width=13, joint="curve")
d.ellipse((108,69,128,89), fill="#ffc176")
d.rounded_rectangle((66,204,179,216), radius=4, fill="#edf5fa")
d.rectangle((60,195,72,225),fill="#ffc176")
d.rectangle((175,195,187,225),fill="#ffc176")
im.save(root / "lab.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
im.save(root / "lab.png")
