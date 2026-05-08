"""
make_icon.py — Generate a proper multi-size scene_doctor.ico from SVG.
Uses Qt to render PNG sizes, then builds the ICO binary manually.
No Pillow required.
"""
import sys
import os
import struct
import io

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODeviceBase
from PySide6.QtSvg import QSvgRenderer

app = QApplication.instance() or QApplication(sys.argv)

script_dir = os.path.dirname(os.path.abspath(__file__))
svg_path = os.path.join(script_dir, "scene_doctor_icon_transparent.svg")

if not os.path.exists(svg_path):
    print(f"ERROR: SVG not found: {svg_path}")
    sys.exit(1)

renderer = QSvgRenderer(svg_path)

# Sizes to include in the ICO
SIZES = [16, 32, 48, 64, 128, 256]

png_datas = []
for size in SIZES:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()

    # Export pixmap to PNG bytes via Qt buffer
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODeviceBase.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    png_bytes = bytes(ba)
    png_datas.append(png_bytes)
    print(f"  Rendered {size}x{size}  ({len(png_bytes)} bytes)")

# --- Build ICO file manually ---
# ICO Header (6 bytes)
num_images = len(SIZES)
header = struct.pack("<HHH", 0, 1, num_images)  # reserved, type=1(ICO), count

# Directory entries come right after header
dir_size = num_images * 16
data_offset = 6 + dir_size

directory = b""
images_blob = b""
current_offset = data_offset

for i, (size, png_bytes) in enumerate(zip(SIZES, png_datas)):
    img_size = len(png_bytes)
    # Width/height: 0 means 256 in ICO format
    w = size if size < 256 else 0
    h = size if size < 256 else 0
    # Each directory entry: BYTE w, BYTE h, BYTE colorCount, BYTE reserved,
    #                        WORD planes, WORD bitCount, DWORD dataSize, DWORD offset
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, img_size, current_offset)
    directory += entry
    images_blob += png_bytes
    current_offset += img_size

ico_data = header + directory + images_blob

# Save
ico_path = os.path.join(script_dir, "scene_doctor.ico")
with open(ico_path, "wb") as f:
    f.write(ico_data)

size_kb = len(ico_data) / 1024
print(f"\nICO saved: {ico_path}  ({size_kb:.1f} KB)  — {num_images} sizes: {SIZES}")
sys.exit(0)
