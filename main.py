import sys
import os
import cv2
import numpy as np
import ctypes
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
                             QLabel, QFileDialog, QHBoxLayout, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QCursor
from PIL import Image, ImageDraw, ImageFont


# Windows 结构体定义
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


class ImageCropper(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('BigYb 智能小图提取器')
        self.setFixedSize(500, 350)
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QWidget { background-color: #1a1a1a; color: #e0e0e0; font-family: "Microsoft YaHei"; }
            QLabel#DropZone {
                border: 2px dashed #444; border-radius: 12px; background-color: #252525;
                color: #888; font-size: 15px; margin: 10px;
            }
            QLabel#DropZone:hover { border-color: #00a2ff; background-color: #2a2a2a; color: #00a2ff; }
            QPushButton {
                background-color: #0078d4; border: none; padding: 12px;
                border-radius: 6px; font-weight: bold; color: white; min-width: 120px;
            }
            QPushButton:hover { background-color: #1e8ad3; }
        """)

        layout = QVBoxLayout()
        self.label = QLabel("将图片拖入此处\n— 或者 —", self)
        self.label.setObjectName("DropZone")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        btn_layout = QHBoxLayout()
        self.btn = QPushButton("选择图片")
        self.btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn.clicked.connect(self.openFileDialog)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files: self.process_image(files[0])

    def openFileDialog(self):
        fname, _ = QFileDialog.getOpenFileName(self, '选择图片', '', '图片文件 (*.jpg *.png *.jpeg)')
        if fname: self.process_image(fname)

    def get_unique_path(self, base_dir, stem, index):
        """核心：递归/循环检查文件名，确保不覆盖"""
        counter = 0
        while True:
            # 第一次尝试：原名_编号.png
            # 后续尝试：原名_编号(1).png, 原名_编号(2).png ...
            suffix = f"({counter})" if counter > 0 else ""
            test_name = f"{stem}_{index}{suffix}.png"
            full_path = os.path.join(base_dir, test_name)
            if not os.path.exists(full_path):
                return full_path
            counter += 1

    def draw_chinese_text(self, img, text, position, font_size, color=(255, 255, 255)):
        img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        try:
            font = ImageFont.truetype("msyh.ttc", int(font_size))
        except:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((position[0] - text_w / 2, position[1] - text_h / 2 - (text_h * 0.1)), text, font=font, fill=color)
        return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    def process_image(self, img_path):
        try:
            img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except:
            img = None

        if img is None:
            QMessageBox.critical(self, "错误", f"无法读取该图片。\n路径: {img_path}")
            return

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edged = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 30, 150)
        dilated = cv2.dilate(edged, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(cnt) for cnt in contours if
                 3 < cv2.boundingRect(cnt)[0] < w - 3 and cv2.boundingRect(cnt)[1] < h - 3 and cv2.boundingRect(cnt)[
                     2] * cv2.boundingRect(cnt)[3] > 1000]

        if not boxes:
            QMessageBox.warning(self, "提示", "未检测到可提取区域")
            return

        selected_indices, status = self.opencv_select_window(img, boxes)
        if status == "SAVE" and selected_indices:
            base_dir = os.path.dirname(img_path)
            file_stem = os.path.splitext(os.path.basename(img_path))[0]

            for i, idx in enumerate(selected_indices):
                bx, by, bw, bh = boxes[idx]
                crop = img[by:by + bh, bx:bx + bw]

                # --- 修改点：调用唯一路径获取函数，防止覆盖 ---
                save_path = self.get_unique_path(base_dir, file_stem, i + 1)

                res, img_encode = cv2.imencode('.png', crop)
                if res: img_encode.tofile(save_path)

            QMessageBox.information(self, "完成", f"已成功提取 {len(selected_indices)} 张图片")

    def opencv_select_window(self, img, boxes):
        selected = []
        status = "PENDING"
        win_name = "BigYb_Select_Window"

        img_h, img_w = img.shape[:2]
        base_size = min(img_h, img_w)
        btn_radius = int(base_size * 0.08)
        margin = int(base_size * 0.05)
        btn_center = [img_w - btn_radius - margin, img_h - btn_radius - margin]
        font_size = int(btn_radius * 0.6)

        is_dragging = [False]
        start_drag_pos = [0, 0]

        user32 = ctypes.windll.user32
        monitor = MONITORINFO()
        monitor.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(0, 1), ctypes.byref(monitor))
        work_w, work_h = monitor.rcWork.right - monitor.rcWork.left, monitor.rcWork.bottom - monitor.rcWork.top

        scale = min((work_w - 40) / img_w, (work_h - 10) / img_h)
        tw, th = int(img_w * scale), int(img_h * scale)

        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(win_name, tw, th)
        cv2.moveWindow(win_name, monitor.rcWork.left + (work_w - tw) // 2, monitor.rcWork.top)

        hwnd = user32.FindWindowW(None, win_name)
        if hwnd:
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            user32.SetForegroundWindow(hwnd)

        def mouse_callback(event, x, y, flags, param):
            nonlocal status
            dist = np.sqrt((x - btn_center[0]) ** 2 + (y - btn_center[1]) ** 2)
            if event == cv2.EVENT_LBUTTONDOWN:
                if dist < btn_radius:
                    is_dragging[0] = True
                    start_drag_pos[0], start_drag_pos[1] = x, y
                else:
                    for i, (bx, by, bw, bh) in enumerate(boxes):
                        if bx <= x <= bx + bw and by <= y <= by + bh:
                            if i in selected:
                                selected.remove(i)
                            else:
                                selected.append(i)
                            break
            elif event == cv2.EVENT_MOUSEMOVE:
                if is_dragging[0]:
                    btn_center[0], btn_center[1] = x, y
            elif event == cv2.EVENT_LBUTTONUP:
                if is_dragging[0]:
                    is_dragging[0] = False
                    if np.sqrt((x - start_drag_pos[0]) ** 2 + (y - start_drag_pos[1]) ** 2) < 8:
                        status = "SAVE"

        cv2.setMouseCallback(win_name, mouse_callback)

        while True:
            temp_img = img.copy()
            overlay = temp_img.copy()
            cv2.circle(overlay, (int(btn_center[0]), int(btn_center[1])), btn_radius, (0, 100, 255), -1)
            cv2.addWeighted(overlay, 0.8, temp_img, 0.2, 0, temp_img)
            temp_img = self.draw_chinese_text(temp_img, "保存", (int(btn_center[0]), int(btn_center[1])), font_size)

            for i, (bx, by, bw, bh) in enumerate(boxes):
                color = (0, 255, 0) if i in selected else (0, 0, 255)
                cv2.rectangle(temp_img, (bx, by), (bx + bw, by + bh), color, int(max(2, base_size * 0.005)))

            if cv2.getWindowProperty(win_name, cv2.WND_PROP_VISIBLE) < 1:
                if status != "SAVE": status = "CANCEL"
                break

            cv2.imshow(win_name, temp_img)
            if status == "SAVE": break
            key = cv2.waitKey(1) & 0xFF
            if key == 32:  # 空格保存
                status = "SAVE"
                break
            if key == 27:  # ESC取消
                status = "CANCEL"
                break

        cv2.destroyAllWindows()
        for _ in range(5): cv2.waitKey(1)
        return selected, status


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ImageCropper()
    ex.show()
    sys.exit(app.exec())