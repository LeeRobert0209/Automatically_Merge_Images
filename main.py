import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QListWidget, QLabel, 
                             QMessageBox, QAbstractItemView, QRadioButton, QButtonGroup,
                             QSlider, QGroupBox, QLineEdit, QTabWidget, QCheckBox)
from PyQt6.QtCore import Qt, QMimeData, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIntValidator, QIcon

from sorter import sort_files
from stitcher import stitch_images
from slicer import slice_image

class StitcherThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, image_paths, output_dir, split_count, target_width, max_kb):
        super().__init__()
        self.image_paths = image_paths
        self.output_dir = output_dir
        self.split_count = split_count
        self.target_width = target_width
        self.max_kb = max_kb

    def run(self):
        try:
            success, message = stitch_images(self.image_paths, self.output_dir, self.split_count, self.target_width, self.max_kb)
            self.finished_signal.emit(success, message)
        except Exception as e:
            self.finished_signal.emit(False, str(e))

class SlicerThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, image_paths, output_dir, count, smart_mode, target_width, max_kb):
        super().__init__()
        self.image_paths = image_paths
        self.output_dir = output_dir
        self.count = count
        self.smart_mode = smart_mode
        self.target_width = target_width
        self.max_kb = max_kb

    def run(self):
        try:
            success_count = 0
            errors = []
            for path in self.image_paths:
                success, msg = slice_image(path, self.output_dir, self.count, self.smart_mode, self.target_width, self.max_kb)
                if success:
                    success_count += 1
                else:
                    errors.append(f"{os.path.basename(path)}: {msg}")
            
            if success_count == len(self.image_paths):
                self.finished_signal.emit(True, f"成功切分所有 {success_count} 张图片。")
            elif success_count > 0:
                error_msg = "\n".join(errors)
                self.finished_signal.emit(True, f"部分成功 ({success_count}/{len(self.image_paths)})。\n失败列表:\n{error_msg}")
            else:
                error_msg = "\n".join(errors)
                self.finished_signal.emit(False, f"所有图片切分失败:\n{error_msg}")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

class ImageMatrixApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageMatrix (影像矩阵) - 拼图 & 切图工具")
        self.setGeometry(100, 100, 650, 750)
        
        # Data storage
        self.merge_images = []
        self.slice_images = []
        
        self.stitch_thread = None
        self.slicer_thread = None

        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Tab 1: Merge
        self.merge_tab = QWidget()
        self.init_merge_tab()
        self.tabs.addTab(self.merge_tab, "拼图 (Merge)")

        # Tab 2: Slice
        self.slice_tab = QWidget()
        self.init_slice_tab()
        self.tabs.addTab(self.slice_tab, "切图 (Slice)")

        # Global Enable Drag & Drop
        self.setAcceptDrops(True)

    def init_merge_tab(self):
        layout = QVBoxLayout(self.merge_tab)

        # Drop Label
        self.merge_drop_label = QLabel("请将图片拖拽到此处\n(支持 .jpg, .jpeg, .png, .psd)")
        self.merge_drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.merge_drop_label.setStyleSheet(self._get_drop_style())
        layout.addWidget(self.merge_drop_label)

        # List Widget
        self.merge_list = QListWidget()
        self.merge_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.merge_list)

        # Controls
        controls_layout = QVBoxLayout()

        # Size Selection
        size_group = QGroupBox("导出宽度选择")
        size_layout = QHBoxLayout()
        
        self.m_radio_original = QRadioButton("原图尺寸 (默认)")
        self.m_radio_750 = QRadioButton("宽度 750px")
        self.m_radio_1080 = QRadioButton("宽度 1080px")
        self.m_radio_original.setChecked(True)

        self.m_radio_custom = QRadioButton("自定义")
        self.m_custom_input = QLineEdit()
        self.m_custom_input.setPlaceholderText("输入宽度")
        self.m_custom_input.setValidator(QIntValidator(1, 20000))
        self.m_custom_input.setFixedWidth(80)
        self.m_custom_input.setEnabled(False)
        self.m_radio_custom.toggled.connect(lambda c: self.m_custom_input.setEnabled(c))
        
        m_size_btn_group = QButtonGroup(self.merge_tab)
        m_size_btn_group.addButton(self.m_radio_original)
        m_size_btn_group.addButton(self.m_radio_750)
        m_size_btn_group.addButton(self.m_radio_1080)
        m_size_btn_group.addButton(self.m_radio_custom)
        
        size_layout.addWidget(self.m_radio_original)
        size_layout.addWidget(self.m_radio_750)
        size_layout.addWidget(self.m_radio_1080)
        size_layout.addWidget(self.m_radio_custom)
        size_layout.addWidget(self.m_custom_input)
        size_group.setLayout(size_layout)
        controls_layout.addWidget(size_group)

        # File Size Limit Selection (New)
        limit_group = QGroupBox("图片大小限制 (KB)")
        limit_layout = QVBoxLayout()
        self.m_limit_label = QLabel("大小限制：200 KB (默认)")
        self.m_limit_slider = QSlider(Qt.Orientation.Horizontal)
        self.m_limit_slider.setMinimum(0)
        self.m_limit_slider.setMaximum(5) # 0, 1, 2, 3, 4, 5 -> Unlimited, 200, 400, 600, 800, 1000
        self.m_limit_slider.setValue(1) # Default 200KB
        self.m_limit_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.m_limit_slider.setTickInterval(1)
        self.m_limit_slider.valueChanged.connect(lambda v: self.update_limit_label(v, self.m_limit_label))
        
        limit_layout.addWidget(self.m_limit_label)
        limit_layout.addWidget(self.m_limit_slider)
        limit_group.setLayout(limit_layout)
        controls_layout.addWidget(limit_group)

        # Split Selection
        split_group = QGroupBox("分组拼接设置")
        split_layout = QVBoxLayout()
        self.m_split_label = QLabel("拼接成：1 张长图")
        self.m_split_slider = QSlider(Qt.Orientation.Horizontal)
        self.m_split_slider.setMinimum(1)
        self.m_split_slider.setMaximum(1)
        self.m_split_slider.valueChanged.connect(lambda v: self.m_split_label.setText(f"拼接成：{v} 张图"))
        
        split_layout.addWidget(self.m_split_label)
        split_layout.addWidget(self.m_split_slider)
        split_group.setLayout(split_layout)
        controls_layout.addWidget(split_group)

        layout.addLayout(controls_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        self.m_clear_btn = QPushButton("清空列表")
        self.m_clear_btn.clicked.connect(self.clear_merge_list)
        btn_layout.addWidget(self.m_clear_btn)

        self.m_start_btn = QPushButton("开始拼接并保存到桌面")
        self.m_start_btn.clicked.connect(self.start_stitching)
        self.m_start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        btn_layout.addWidget(self.m_start_btn)

        layout.addLayout(btn_layout)

    def init_slice_tab(self):
        layout = QVBoxLayout(self.slice_tab)

        # Drop Label
        self.slice_drop_label = QLabel("请将需切割的图片拖拽到此处\n(支持 .jpg, .png, .psd)")
        self.slice_drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slice_drop_label.setStyleSheet(self._get_drop_style())
        layout.addWidget(self.slice_drop_label)

        # List Widget
        self.slice_list = QListWidget()
        layout.addWidget(self.slice_list)

        # Controls
        controls_layout = QVBoxLayout()

        # 1. Width Selection (Similar to Merge)
        size_group = QGroupBox("切分后宽度")
        size_layout = QHBoxLayout()
        
        self.s_radio_original = QRadioButton("原图宽度 (默认)")
        self.s_radio_custom = QRadioButton("指定宽度")
        self.s_radio_original.setChecked(True)
        
        self.s_custom_input = QLineEdit()
        self.s_custom_input.setPlaceholderText("例如 750")
        self.s_custom_input.setValidator(QIntValidator(1, 20000))
        self.s_custom_input.setFixedWidth(80)
        self.s_custom_input.setEnabled(False)
        self.s_radio_custom.toggled.connect(lambda c: self.s_custom_input.setEnabled(c))

        s_size_btn_group = QButtonGroup(self.slice_tab)
        s_size_btn_group.addButton(self.s_radio_original)
        s_size_btn_group.addButton(self.s_radio_custom)

        size_layout.addWidget(self.s_radio_original)
        size_layout.addWidget(self.s_radio_custom)
        size_layout.addWidget(self.s_custom_input)
        size_layout.addStretch() # Push to left
        size_group.setLayout(size_layout)
        controls_layout.addWidget(size_group)

        # 2. File Size Limit Selection (New)
        limit_group = QGroupBox("切片图片大小限制 (KB)")
        limit_layout = QVBoxLayout()
        self.s_limit_label = QLabel("大小限制：200 KB (默认)")
        self.s_limit_slider = QSlider(Qt.Orientation.Horizontal)
        self.s_limit_slider.setMinimum(0)
        self.s_limit_slider.setMaximum(5)
        self.s_limit_slider.setValue(1) # Default 200KB
        self.s_limit_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.s_limit_slider.setTickInterval(1)
        self.s_limit_slider.valueChanged.connect(lambda v: self.update_limit_label(v, self.s_limit_label))
        
        limit_layout.addWidget(self.s_limit_label)
        limit_layout.addWidget(self.s_limit_slider)
        limit_group.setLayout(limit_layout)
        controls_layout.addWidget(limit_group)

        # 3. Slice Settings
        slice_group = QGroupBox("切图设置")
        slice_inner_layout = QVBoxLayout()

        # Count Slider
        count_layout = QHBoxLayout()
        self.s_count_label = QLabel("纵向切成：5 份 (每份高度自动计算)")
        self.s_count_slider = QSlider(Qt.Orientation.Horizontal)
        self.s_count_slider.setMinimum(1)
        self.s_count_slider.setMaximum(50)
        self.s_count_slider.setValue(5)
        self.s_count_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.s_count_slider.setTickInterval(5)
        self.s_count_slider.valueChanged.connect(self.update_slice_label)
        
        count_layout.addWidget(self.s_count_label)
        slice_inner_layout.addLayout(count_layout)
        slice_inner_layout.addWidget(self.s_count_slider)

        # Smart Checkbox
        self.s_smart_check = QCheckBox("智能自动吸附 (推荐)")
        self.s_smart_check.setToolTip("开启后，将自动寻找图片中的空白或分隔线进行切割，\n避免切断文字或产品。")
        self.s_smart_check.setChecked(True)
        slice_inner_layout.addWidget(self.s_smart_check)

        slice_group.setLayout(slice_inner_layout)
        controls_layout.addWidget(slice_group)

        layout.addLayout(controls_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        self.s_clear_btn = QPushButton("清空列表")
        self.s_clear_btn.clicked.connect(self.clear_slice_list)
        btn_layout.addWidget(self.s_clear_btn)

        self.s_start_btn = QPushButton("开始切图并保存到桌面")
        self.s_start_btn.clicked.connect(self.start_slicing)
        self.s_start_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 10px;")
        btn_layout.addWidget(self.s_start_btn)

        layout.addLayout(btn_layout)

    def _get_drop_style(self):
        return """
            QLabel {
                border: 2px dashed #aaa;
                border-radius: 10px;
                padding: 15px;
                font-size: 14px;
                color: #555;
                background-color: #f0f0f0;
            }
        """

    def update_slice_label(self, value):
        self.s_count_label.setText(f"纵向切成：{value} 份 (每份高度自动计算)")

    def update_limit_label(self, value, label_widget):
        kb_val = value * 200
        if value == 0:
            label_widget.setText("大小限制：不限制")
        else:
            if kb_val >= 1000:
                label_widget.setText(f"大小限制：1 MB")
            else:
                label_widget.setText(f"大小限制：{kb_val} KB")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        valid_extensions = ('.jpg', '.jpeg', '.png', '.psd')
        new_images = [f for f in files if f.lower().endswith(valid_extensions)]

        if not new_images:
            QMessageBox.warning(self, "无效文件", "请只拖入支持的图片文件 (.jpg, .png, .psd)")
            return

        current_index = self.tabs.currentIndex()
        if current_index == 0: # Merge Tab
            combined_set = set(self.merge_images + new_images)
            self.merge_images = sort_files(list(combined_set))
            self.update_merge_list()
            self.m_split_slider.setMaximum(max(1, len(self.merge_images)))
        else: # Slice Tab
            # For slicing, order matters less, just append
            for img in new_images:
                if img not in self.slice_images:
                    self.slice_images.append(img)
            self.update_slice_list()

    def update_merge_list(self):
        self.merge_list.clear()
        for path in self.merge_images:
            self.merge_list.addItem(os.path.basename(path))

    def update_slice_list(self):
        self.slice_list.clear()
        for path in self.slice_images:
            self.slice_list.addItem(os.path.basename(path))

    def clear_merge_list(self):
        self.merge_images = []
        self.merge_list.clear()
        self.m_split_slider.setMaximum(1)
        self.m_split_slider.setValue(1)

    def clear_slice_list(self):
        self.slice_images = []
        self.slice_list.clear()

    # --- Actions ---

    def start_stitching(self):
        if not self.merge_images:
            QMessageBox.warning(self, "提示", "请先添加图片！")
            return

        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        
        # Get settings
        split_count = self.m_split_slider.value()
        
        target_width = None
        if self.m_radio_750.isChecked():
            target_width = 750
        elif self.m_radio_1080.isChecked():
            target_width = 1080
        elif self.m_radio_custom.isChecked():
            try:
                val_text = self.m_custom_input.text().strip()
                if not val_text: raise ValueError
                target_width = int(val_text)
            except ValueError:
                QMessageBox.warning(self, "输入错误", "请输入有效的宽度！")
                return

        # Get Limit
        limit_val = self.m_limit_slider.value() * 200 # 0 -> 0, 1 -> 200 ...
        
        self.m_start_btn.setEnabled(False)
        self.m_start_btn.setText("正在拼接... ")
        
        self.stitch_thread = StitcherThread(self.merge_images, desktop_path, split_count, target_width, limit_val)
        self.stitch_thread.finished_signal.connect(self.on_stitching_finished)
        self.stitch_thread.start()

    def on_stitching_finished(self, success, message):
        self.m_start_btn.setEnabled(True)
        self.m_start_btn.setText("开始拼接并保存到桌面")
        if success:
            QMessageBox.information(self, "成功", f"{message}\n已保存到桌面。")
        else:
            QMessageBox.critical(self, "错误", f"拼接失败：\n{message}")

    def start_slicing(self):
        if not self.slice_images:
            QMessageBox.warning(self, "提示", "请先添加要切分的图片！")
            return

        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        
        # Settings
        count = self.s_count_slider.value()
        smart_mode = self.s_smart_check.isChecked()
        
        target_width = None
        target_width = None
        if self.s_radio_custom.isChecked():
            val_text = self.s_custom_input.text().strip()
            if not val_text:
                # User left it empty, use default placeholder value
                target_width = 750
            else:
                try:
                    target_width = int(val_text)
                except ValueError:
                    QMessageBox.warning(self, "输入错误", "请输入有效的宽度！")
                    return

        # Get Limit
        limit_val = self.s_limit_slider.value() * 200

        self.s_start_btn.setEnabled(False)
        self.s_start_btn.setText("正在切图... ")
        
        self.slicer_thread = SlicerThread(self.slice_images, desktop_path, count, smart_mode, target_width, limit_val)
        self.slicer_thread.finished_signal.connect(self.on_slicing_finished)
        self.slicer_thread.start()

    def on_slicing_finished(self, success, message):
        self.s_start_btn.setEnabled(True)
        self.s_start_btn.setText("开始切图并保存到桌面")
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "注意", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageMatrixApp()
    window.show()
    sys.exit(app.exec())
