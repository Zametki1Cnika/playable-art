"""Draw a simple demo leg (pelvis, trouser leg, boot) so the tool can be tried without your own art.

python make_demo_leg.py demo_leg.png
"""

import sys

from PIL import Image, ImageDraw

W, H = 512, 360
im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
dark, cloth, light, boot, boot_hi = (26, 31, 28, 255), (88, 98, 66, 255), (112, 122, 84, 255), (40, 44, 36, 255), (62, 68, 54, 255)
# pelvis
d.rounded_rectangle((206, 18, 290, 70), 14, fill=cloth, outline=dark, width=3)
# thigh and shin (trousers), slightly tapered
d.polygon([(214, 56), (288, 56), (276, 170), (226, 172)], fill=cloth, outline=dark)
d.polygon([(226, 166), (276, 166), (268, 232), (232, 232)], fill=cloth, outline=dark)
d.line([(236, 70), (240, 160)], fill=light, width=6)
d.arc((222, 150, 280, 190), 200, 340, fill=dark, width=2)
# boot
d.polygon([(230, 226), (270, 226), (268, 318), (232, 318)], fill=boot, outline=dark)
d.polygon([(228, 312), (300, 312), (316, 330), (316, 340), (226, 340)], fill=boot, outline=dark)
d.line([(238, 236), (238, 312)], fill=boot_hi, width=4)
im.save(sys.argv[1] if len(sys.argv) > 1 else "demo_leg.png")
print("ok")
