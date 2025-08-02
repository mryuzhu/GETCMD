import sys

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        msg = " ".join(str(a) for a in args)
        print(msg.encode('gbk', errors='replace').decode('gbk'), **kwargs)

import argparse
import json, os, subprocess, urllib.parse
import threading  # 已有，无需重复导入
import serial  # 需 pip install pyserial
import time       # 已有，无需重复导入
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QMessageBox, QComboBox,
    QFileDialog, QDialog, QLabel, QDialogButtonBox, QAction, QInputDialog,
    QSystemTrayIcon, QMenu, QCheckBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon  # 新增导入
from PyQt5.QtCore import Qt  # 新增导入
from PyQt5.QtCore import QTimer
import paho.mqtt.client as mqtt
#作者羽竹and chatgpt4.1
class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("日志输出")
        self.resize(600, 400)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)

    def append_log(self, msg):
        self.text_edit.append(msg)
# 修改配置文件路径为用户目录
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "launcher_config.json")

MUSIC_PLATFORMS = {
    "网易云音乐": "ncm://start.weixin",
    "酷狗音乐": "kugou://start.weixin",
    "酷我音乐": "kuwo://start.weixin",
    "QQ音乐": "qqmusic://start.weixin",
    "Apple Music": "applemusic://start.weixin"
}

# ---------------- 配置读写 ----------------
def load_config():
    """
    从配置文件读取启动项配置，返回字典。
    """
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_config(cfg):
    """
    将启动项配置写入配置文件。
    """
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

# ---------------- 编辑对话框 ----------------
class EditDialog(QDialog):
    """
    添加/编辑启动项的对话框。
    """
    def __init__(self, parent=None, name=None, cfg=None):
        super().__init__(parent)
        self.setWindowTitle("添加/编辑")
        self.resize(400, 260)

        # 名称输入框
        self.name_edit = QLineEdit(name or "")
        # 类型下拉框（exe/adb/music）
        self.type_combo = QComboBox()
        self.type_combo.addItems(["exe", "adb", "music", "brightness"])
        # 路径/命令输入框
        self.cmd_edit = QTextEdit(cfg["cmd"] if cfg else "")

        # 新增音乐平台协议输入框
        self.uri_scheme_edit = QLineEdit()
        self.uri_scheme_edit.setPlaceholderText("如 kugou://start.weixin")
        if cfg and "uri_scheme" in cfg:
            self.uri_scheme_edit.setText(cfg["uri_scheme"])
        else:
            self.uri_scheme_edit.setText("kugou://start.weixin")

        # 新增卡号输入框
        self.card_id_edit = QLineEdit(cfg.get("card_id", "") if cfg else "")
        self.card_id_edit.setPlaceholderText("可选，刷卡器卡号或多个卡号用英文逗号分隔")

        # 新增：巴法云Topic输入框
        self.bafy_topic_edit = QLineEdit(cfg.get("bafy_topic", "") if cfg else "")
        self.bafy_topic_edit.setPlaceholderText("可选，巴法云Topic，云端按钮控制")
        
        form = QVBoxLayout(self)
        form.addWidget(QLabel("名称："))
        form.addWidget(self.name_edit)
        form.addWidget(QLabel("类型："))
        form.addWidget(self.type_combo)
        form.addWidget(QLabel("音乐平台协议（仅music类型需填）："))
        form.addWidget(self.uri_scheme_edit)
        form.addWidget(QLabel("路径 / 命令 / 音乐JSON："))
        form.addWidget(self.cmd_edit)
        form.addWidget(QLabel("绑定卡号（可选，多个用英文逗号分隔）："))
        form.addWidget(self.card_id_edit)
        form.addWidget(QLabel("巴法云Topic（可选，云端按钮控制）："))
        form.addWidget(self.bafy_topic_edit)

        if cfg:
            self.type_combo.setCurrentText(cfg["type"])
            if cfg["type"] == "exe":
                browse_btn = QPushButton("浏览...")
                browse_btn.clicked.connect(self.browse_exe)
                form.addWidget(browse_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addWidget(buttons)

    def browse_exe(self):
        """
        弹出文件选择对话框，选择exe文件。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择可执行文件", "", "可执行文件 (*.exe)")
        if file_path:
            self.cmd_edit.setPlainText(file_path.replace("/", "\\"))

    def get_data(self):
        """
        获取对话框中填写的数据。
        """
        return {
            "type": self.type_combo.currentText(),
            "cmd": self.cmd_edit.toPlainText().strip(),
            "uri_scheme": self.uri_scheme_edit.text().strip(),
            "card_id": self.card_id_edit.text().strip(),
            "bafy_topic": self.bafy_topic_edit.text().strip()  # 新增
        }

# ---------------- 设置对话框 ----------------
class SettingsDialog(QDialog):
    """
    设置对话框：可设置首选音乐平台、ADB设备IP、巴法云UID和Topic
    """
    def __init__(self, parent=None, default_platform="酷狗音乐", default_ip="", default_serial="COM3", default_uid="", default_topic="", default_enable_card=True, default_enable_adb=True, default_music_screen_on=True, default_adb_screen_on=True, default_unlock_after_screen_on=False, default_device_password=""):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(320, 240)
        layout = QVBoxLayout(self)

        # 音乐平台下拉框
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(MUSIC_PLATFORMS.keys())
        self.platform_combo.setCurrentText(default_platform)
        layout.addWidget(QLabel("首选音乐平台："))
        layout.addWidget(self.platform_combo)

        # ADB IP输入框
        self.ip_edit = QLineEdit(default_ip)
        self.ip_edit.setPlaceholderText("如 192.168.1.123")
        layout.addWidget(QLabel("ADB设备IP："))
        layout.addWidget(self.ip_edit)

        # 巴法云UID
        self.uid_edit = QLineEdit(default_uid)
        self.uid_edit.setPlaceholderText("巴法云UID（必填）")
        layout.addWidget(QLabel("巴法云UID："))
        layout.addWidget(self.uid_edit)

        # 巴法云Topic
        self.topic_edit = QLineEdit(default_topic)
        self.topic_edit.setPlaceholderText("巴法云Topic（如 yourTopic006）")
        layout.addWidget(QLabel("巴法云Topic："))
        layout.addWidget(self.topic_edit)

        # 串口号输入框
        self.serial_port_edit = QLineEdit(default_serial)
        self.serial_port_edit.setPlaceholderText("如 COM3")
        layout.addWidget(QLabel("读卡器串口号："))
        layout.addWidget(self.serial_port_edit)

        # 读卡器开关
        self.enable_card_reader = QCheckBox("启用读卡器")
        self.enable_card_reader.setChecked(default_enable_card if default_enable_card is not None else True)
        layout.addWidget(self.enable_card_reader)

        # 启动时ADB连接开关
        self.enable_adb_connect = QCheckBox("启动时进行ADB连接")
        self.enable_adb_connect.setChecked(default_enable_adb if default_enable_adb is not None else True)
        layout.addWidget(self.enable_adb_connect)

        # 新增：音乐和ADB前亮屏选项
        self.music_screen_on = QCheckBox("播放音乐前亮屏")
        self.music_screen_on.setChecked(default_music_screen_on)
        layout.addWidget(self.music_screen_on)

        self.adb_screen_on = QCheckBox("adb前亮屏")
        self.adb_screen_on.setChecked(default_adb_screen_on)
        layout.addWidget(self.adb_screen_on)

        # 新增：亮屏后解锁设备选项
        self.unlock_after_screen_on = QCheckBox("亮屏后解锁设备")
        self.unlock_after_screen_on.setChecked(default_unlock_after_screen_on if default_unlock_after_screen_on is not None else False)
        layout.addWidget(self.unlock_after_screen_on)

        # 设备密码输入框（密码模式）
        self.device_password_edit = QLineEdit(default_device_password if default_device_password else "")
        self.device_password_edit.setPlaceholderText("设备解锁密码")
        self.device_password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("设备解锁密码："))
        layout.addWidget(self.device_password_edit)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return (
            self.platform_combo.currentText(),
            self.ip_edit.text().strip(),
            self.serial_port_edit.text().strip(),
            self.uid_edit.text().strip(),
            self.topic_edit.text().strip(),
            self.enable_card_reader.isChecked(),
            self.enable_adb_connect.isChecked(),
            self.music_screen_on.isChecked(),
            self.adb_screen_on.isChecked(),
            self.unlock_after_screen_on.isChecked(),
            self.device_password_edit.text().strip()
        )

# ---------------- 主窗口 ----------------
class Launcher(QMainWindow):
    """
    启动器主窗口，显示所有启动项。
    """
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon("icon.ico"))  # 设置主窗口和任务栏图标
        self.cfg = load_config()
        # 自动添加“关机”启动项
        if "关机" not in self.cfg:
            self.cfg["关机"] = {
                "type": "exe",
                "cmd": "shutdown -s -t 60",
                "uri_scheme": "",
                "card_id": "",
                "bafy_topic": "off001"  # 这里改为 off001
            }
            save_config(self.cfg)
        # 自动添加“设置亮度”启动项
        if "设置亮度" not in self.cfg:
            self.cfg["设置亮度"] = {
                "type": "brightness",
                "cmd": 'WMIC /NAMESPACE:\\\\root\\wmi PATH WmiMonitorBrightnessMethods WHERE "Active=TRUE" CALL WmiSetBrightness Brightness=XXX Timeout=0',
                "uri_scheme": "",
                "card_id": "",
                "bafy_topic": "brightness002"
            }
        # 自动添加“酷狗示例”启动项
        if "酷狗示例" not in self.cfg:
            self.cfg["邓紫棋-喜欢你"] = {
                "type": "music",
                "cmd": "{\n    \"cmd\": 212,\n    \"jsonStr\": {\n        \"bitrate\": 128,\n        \"duration\": 239,\n        \"extname\": \"mp3\",\n        \"filename\": \"G.E.M. 邓紫棋 - 喜欢你\",\n        \"hash\": \"cff4d61fa1318100ce18a88ebb52e335\"\n    }\n}",
                "uri_scheme": "kugou://start.weixin",
                "card_id": "",
                "bafy_topic": ""
            }

            save_config(self.cfg)
        self.last_card_time = 0  # 刷卡防抖
        self.mqtt_clients = {}  # topic: client
        self.current_page = 0  # 新增：当前页
        self.items_per_page = 10  # 新增：每页显示数量
        self.init_ui()
        if self.cfg.get("_enable_adb_connect", True):
            self.connect_device()
        if self.cfg.get("_enable_card_reader", True):
            self.start_card_reader_thread()
        self.init_tray()
        self.start_bafy_mqtt_listener()  # 新增：启动MQTT监听
    def parse_args():
        """解析命令行参数"""
        parser = argparse.ArgumentParser()
        parser.add_argument("-d", "--daemon", action="store_true", help="后台运行")
        return parser.parse_args()

    def init_ui(self):
        """
        初始化主界面。
        """
        self.setWindowTitle("启动器")
        self.setGeometry(100, 100, 340, 480)

        # 菜单栏添加设置、解析器、连接设备
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")
        action_settings = QAction("设置", self)
        action_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(action_settings)

        # 解析器按钮
        action_parser = QAction("酷狗音乐解析器", self)
        action_parser.triggered.connect(self.open_parser)
        menubar.addAction(action_parser)

        # 连接设备按钮
        action_connect = QAction("连接设备", self)
        action_connect.triggered.connect(self.connect_device)
        menubar.addAction(action_connect)

        self.central = QWidget()
        self.vbox = QVBoxLayout(self.central)
        self.setCentralWidget(self.central)

        self.add_btn = QPushButton("+ 新建")
        self.add_btn.clicked.connect(self.add_item)
        self.vbox.addWidget(self.add_btn)

        # 新增：分页按钮
        hbox = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.prev_page)
        hbox.addWidget(self.prev_btn)
        self.page_label = QLabel()
        hbox.addWidget(self.page_label)
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        hbox.addWidget(self.next_btn)
        self.vbox.addLayout(hbox)

        self.refresh_ui()

        # 右下角加一小段文字
        copyright_label = QLabel("by mryuzhu")
        copyright_label.setStyleSheet("color: gray; font-size: 15px;")
        copyright_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.vbox.addWidget(copyright_label)

    def open_settings(self):
        cfg = load_config()
        default_platform = cfg.get("_music_platform", "酷狗音乐")
        default_ip = cfg.get("_adb_ip", "")
        default_serial = cfg.get("_serial_port", "COM3")
        default_uid = cfg.get("_bafy_uid", "")
        default_topic = cfg.get("_bafy_topic", "")
        default_enable_card = cfg.get("_enable_card_reader", True)
        default_enable_adb = cfg.get("_enable_adb_connect", True)
        default_music_screen_on = cfg.get("_music_screen_on", True)
        default_adb_screen_on = cfg.get("_adb_screen_on", True)
        default_unlock_after_screen_on = cfg.get("_unlock_after_screen_on", False)
        default_device_password = cfg.get("_device_password", "")
        dlg = SettingsDialog(self, default_platform, default_ip, default_serial, default_uid, default_topic, default_enable_card, default_enable_adb, default_music_screen_on, default_adb_screen_on, default_unlock_after_screen_on, default_device_password)
        if dlg.exec_() == QDialog.Accepted:
            (platform, ip, serial_port, uid, topic, enable_card, enable_adb, music_screen_on, adb_screen_on, unlock_after_screen_on, device_password) = dlg.get_values()
            cfg["_music_platform"] = platform
            cfg["_adb_ip"] = ip
            cfg["_serial_port"] = serial_port
            cfg["_bafy_uid"] = uid
            cfg["_bafy_topic"] = topic
            cfg["_enable_card_reader"] = enable_card
            cfg["_enable_adb_connect"] = enable_adb
            cfg["_music_screen_on"] = music_screen_on
            cfg["_adb_screen_on"] = adb_screen_on
            cfg["_unlock_after_screen_on"] = unlock_after_screen_on
            cfg["_device_password"] = device_password
            save_config(cfg)
            QMessageBox.information(self, "设置", f"已保存设置！")

    def connect_device(self):
        # 从配置读取IP
        cfg = load_config()
        ip = getattr(self, "adb_ip", None) or cfg.get("_adb_ip", "")
        if not ip:
            QMessageBox.warning(self, "未设置IP", "请先在设置中填写ADB设备IP。")
            return
        cmd = f'adb connect {ip}'
        try:
            result = subprocess.run(cmd, shell=True,creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            print("stdout:", result.stdout)
            print("stderr:", result.stderr)
            if result.returncode == 0:
                QMessageBox.information(self, "连接成功", result.stdout)
            else:
                QMessageBox.critical(self, "连接失败", result.stderr or result.stdout)
        except Exception as e:
            self.show_error_message("错误", f"命令执行失败: {e}")

    def start_card_reader_thread(self):
        """
        启动后台线程监听串口读卡器。
        """
        def reader():
            try:
                cfg = load_config()
                serial_port = cfg.get("_serial_port", "COM3")
                ser = serial.Serial(serial_port, 9600, timeout=1)
                while True:
                    data = ser.readline().decode(errors="ignore").strip()
                    if data:
                        self.handle_card_id(data)
                    time.sleep(0.1)
            except Exception as e:
                print("读卡器初始化失败:", e)

        t = threading.Thread(target=reader, daemon=True)
        t.start()

    def handle_card_id(self, card_id):
        """
        处理刷卡事件，自动匹配并执行启动项。
        支持多个卡号用英文逗号分隔。
        """
        print("读取到卡号:", card_id)
        for name, info in self.cfg.items():
            if name.startswith("_"):
                continue
            card_ids = [x.strip() for x in info.get("card_id", "").split(",") if x.strip()]
            if card_id in card_ids:
                print(f"卡号 {card_id} 匹配到启动项：{name}，自动执行。")
                self.run_item(name)
                break

    def refresh_ui(self):
        """
        刷新启动项列表UI，支持分组显示。
        """
        # 清除旧的按钮和布局，确保对象能被回收
        for i in reversed(range(self.vbox.count())):
            item = self.vbox.itemAt(i)
            widget = item.widget()
            layout = item.layout()
            if widget and widget not in [self.add_btn, self.prev_btn, self.next_btn, self.page_label]:
                widget.deleteLater()
                self.vbox.removeWidget(widget)
            elif layout and layout not in [self.vbox.itemAt(self.vbox.count()-1)]:
                while layout.count():
                    child = layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                self.vbox.removeItem(layout)
                del layout

        # 获取所有启动项（不含下划线开头的）
        items = [(name, info) for name, info in self.cfg.items() if not name.startswith("_")]
        total = len(items)
        total_pages = max(1, (total + self.items_per_page - 1) // self.items_per_page)
        self.current_page = max(0, min(self.current_page, total_pages - 1))
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = items[start:end]

        for name, info in page_items:
            hbox = QHBoxLayout()
            btn = QPushButton(name)
            btn.clicked.connect(self._make_run_item(name))
            hbox.addWidget(btn)
            edit_btn = QPushButton("✏️")
            edit_btn.setFixedWidth(30)
            edit_btn.clicked.connect(self._make_edit_item(name))
            hbox.addWidget(edit_btn)
            del_btn = QPushButton("🗑️")
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(self._make_delete_item(name))
            hbox.addWidget(del_btn)
            self.vbox.insertLayout(self.vbox.count() - 1, hbox)  # 保证分页按钮在最下方

        # 更新分页标签
        self.page_label.setText(f"第 {self.current_page+1} / {total_pages} 页")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_ui()

    def next_page(self):
        items = [(name, info) for name, info in self.cfg.items() if not name.startswith("_")]
        total_pages = max(1, (len(items) + self.items_per_page - 1) // self.items_per_page)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh_ui()

    def open_parser(self):
        """
        解析器：将带协议的音乐启动链接还原为 JSON。
        """
        text, ok = QInputDialog.getMultiLineText(self, "解析器", "输入带协议的音乐启动链接：")
        if not ok or not text.strip():
            return

        import re
        import urllib.parse

        # 提取问号后的内容
        match = re.search(r'\?(.*)$', text.strip())
        if not match:
            QMessageBox.warning(self, "解析失败", "未找到 ? 后的内容")
            return

        encoded = match.group(1).strip()
        # 尝试解码
        try:
            decoded = urllib.parse.unquote(encoded)
            # 预处理：去掉所有多余的反斜杠
            decoded = decoded.replace('\\', '')
            # 再尝试转为 JSON
            try:
                obj = json.loads(decoded)
            except Exception:
                # 兼容直接写Python字典的情况
                obj = eval(decoded)
            formatted = json.dumps(obj, ensure_ascii=False, indent=4)
            # 显示结果
            dlg = QDialog(self)
            dlg.setWindowTitle("解析结果")
            vbox = QVBoxLayout(dlg)
            edit = QTextEdit()
            edit.setPlainText(formatted)
            vbox.addWidget(edit)
            btns = QDialogButtonBox(QDialogButtonBox.Ok)
            btns.accepted.connect(dlg.accept)
            vbox.addWidget(btns)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"错误: {e}")

    def add_item(self):
        """
        新建启动项的对话框逻辑。
        """
        dlg = EditDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            name = dlg.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "提示", "名称不能为空！")
                return
            self.cfg[name] = data
            save_config(self.cfg)
            self.refresh_ui()

    def send_bafy_on(self):
        """
        发送“开”指令到巴法云（全局Topic）。
        """
        cfg = load_config()
        topic = cfg.get("_bafy_topic", "")
        uid = cfg.get("_bafy_uid", "")
        if not topic or not uid:
            QMessageBox.warning(self, "提示", "请先在设置中填写巴法云UID和Topic。")
            return
        client = mqtt.Client(client_id=uid)
        try:
            client.connect("bemfa.com", 9501, 60)
            client.publish(topic, "on")
            client.disconnect()
            QMessageBox.information(self, "提示", f"已发送“开”指令到Topic: {topic}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"发送失败: {e}")

    def send_bafy_off(self):
        """
        发送“关”指令到巴法云（全局Topic）。
        """
        cfg = load_config()
        topic = cfg.get("_bafy_topic", "")
        uid = cfg.get("_bafy_uid", "")
        if not topic or not uid:
            QMessageBox.warning(self, "提示", "请先在设置中填写巴法云UID和Topic。")
            return
        client = mqtt.Client(client_id=uid)
        try:
            client.connect("bemfa.com", 9501, 60)
            client.publish(topic, "off")
            client.disconnect()
            QMessageBox.information(self, "提示", f"已发送“关”指令到Topic: {topic}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"发送失败: {e}")

    def _make_run_item(self, name):
        def run():
            self.run_item(name)
        return run

    def _make_edit_item(self, name):
        def edit():
            cfg = self.cfg[name]
            dlg = EditDialog(self, name, cfg)
            if dlg.exec_() == QDialog.Accepted:
                self.cfg[name] = dlg.get_data()
                save_config(self.cfg)
                self.refresh_ui()
        return edit

    def _make_delete_item(self, name):
        def delete():
            reply = QMessageBox.question(self, "确认", f"确定要删除启动项“{name}”吗？", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.cfg.pop(name, None)
                save_config(self.cfg)
                self.refresh_ui()
        return delete

    def run_item(self, name, brightness_value=None):
        info = self.cfg.get(name)
        if not info:
            QMessageBox.warning(self, "提示", f"未找到启动项：{name}")
            return
        item_type = info["type"].strip().lower()
        safe_print(f"run_item: name={name}, type={item_type}")

        def try_screen_on():
            try:
                if is_screen_on() is not True:
                    safe_print("屏幕未点亮，尝试亮屏")
                    subprocess.Popen("adb shell input keyevent KEYCODE_POWER", shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    time.sleep(1)
                    # 亮屏后解锁
                    unlock = self.cfg.get("_unlock_after_screen_on", False)
                    pwd = self.cfg.get("_device_password", "")
                    safe_print(f"解锁开关: {unlock}, 密码: {'有' if pwd else '无'}")
                    if unlock:
                        if pwd:
                            safe_print("亮屏后自动解锁设备")
                            subprocess.Popen(f'adb shell input text "{pwd}"', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                            time.sleep(1)
                else:
                    safe_print("屏幕已点亮，无需亮屏")
            except Exception as e:
                safe_print("亮屏检测失败，尝试亮屏", e)
                subprocess.Popen("adb shell input keyevent KEYCODE_POWER", shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(1)
                unlock = self.cfg.get("_unlock_after_screen_on", False)
                pwd = self.cfg.get("_device_password", "")
                safe_print(f"解锁开关: {unlock}, 密码: {'有' if pwd else '无'}")
                if unlock:
                    if pwd:
                        safe_print("亮屏后自动解锁设备")
                        subprocess.Popen(f'adb shell input text "{pwd}"', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        time.sleep(1)

        if item_type == "exe":
            cmds = info["cmd"].splitlines()
            def run_cmds():
                for idx, cmd in enumerate(cmds):
                    cmd = cmd.strip()
                    if not cmd:
                        continue
                    safe_print(f"执行命令: {cmd}")
                    try:
                        subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception as e:
                        self.show_error_message("错误", f"命令执行失败: {e}")
                    if idx < len(cmds) - 1:
                        time.sleep(1)
            threading.Thread(target=run_cmds, daemon=True).start()
        elif item_type == "adb":
            if self.cfg.get("_adb_screen_on", True):
               try_screen_on()
            cmds = info["cmd"].splitlines()
            def run_cmds():
                for idx, cmd in enumerate(cmds):
                    cmd = cmd.strip()
                    if not cmd:
                      continue
                    safe_print(f"执行命令: {cmd}")
                    try:
                        import shlex
                        if cmd.startswith("adb "):
                            cmd_list = shlex.split(cmd)
                            subprocess.Popen(cmd_list, creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception as e:
                        self.show_error_message("错误", f"命令执行失败: {e}")
                    if idx < len(cmds) - 1:
                        time.sleep(1)
            threading.Thread(target=run_cmds, daemon=True).start()
        elif item_type == "music":
            if self.cfg.get("_music_screen_on", True):
                try_screen_on()
            try:
                cmd_data = info.get("cmd", "")
                # 如果cmd_data看起来像完整URI，直接用
                if isinstance(cmd_data, str) and (cmd_data.startswith("orpheus://") or cmd_data.startswith("ncm://") or cmd_data.startswith("qqmusic://") or cmd_data.startswith("kugou://") or cmd_data.startswith("kuwo://") or cmd_data.startswith("music://")):
                    final_uri = cmd_data
                else:
                    # 兼容原有JSON格式
                    if isinstance(cmd_data, str):
                        try:
                            music_json = json.loads(cmd_data)
                        except Exception:
                            music_json = eval(cmd_data)
                    else:
                        music_json = cmd_data
                    json_str = json.dumps(music_json, ensure_ascii=False)
                    encoded_uri = urllib.parse.quote(json_str)
                    scheme = info.get("uri_scheme", "kugou://start.weixin")
                    final_uri = f'{scheme}?{encoded_uri}'
                adb_cmd = f'adb shell am start -a android.intent.action.VIEW -d "{final_uri}"'
                safe_print(f"执行命令：{adb_cmd}")
                subprocess.Popen(adb_cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"音乐启动失败：{e}")
        elif item_type == "brightness":
            cmd_template = info["cmd"]
            if brightness_value is not None:
                value = brightness_value
                ok = True
            else:
                value, ok = QInputDialog.getInt(self, "设置亮度", "请输入亮度（0-100）：", 50, 0, 100)
            if ok:
                cmd = cmd_template.replace("XXX", str(value))
                print(f"执行亮度命令: {cmd}")
                try:
                    subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"亮度设置失败: {e}")

    def init_tray(self):
        # 托盘图标
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon("icon.ico"))
        self.tray.setToolTip("启动器 by mryuzhu")

        # 托盘菜单
        menu = QMenu()
        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self.showNormal)
        menu.addAction(show_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event):
        # 重写关闭事件，隐藏窗口到托盘而不是退出
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "启动器已最小化",
            "程序仍在后台运行，点击托盘图标可恢复窗口。",
            QSystemTrayIcon.Information,
            2000
        )

    def start_bafy_mqtt_listener(self):
        """
        启动MQTT客户端，监听所有配置中出现过的bafy_topic。
        """
        topics = set()
        # 收集所有启动项的bafy_topic
        for name, info in self.cfg.items():
            if name.startswith("_"):
                continue
            topic = info.get("bafy_topic")
            if topic:
                topics.add(topic)
        # 也可加全局topic
        global_topic = self.cfg.get("_bafy_topic", "")
        if global_topic:
            topics.add(global_topic)

        uid = self.cfg.get("_bafy_uid", "")
        if not uid or not topics:
            print("未配置巴法云UID或Topic，MQTT监听未启动")
            return

        def on_connect(client, userdata, flags, rc):
            print("MQTT连接结果:", rc)
            for t in topics:
                client.subscribe(t)
                print(f"已订阅: {t}")

        def on_message(client, userdata, msg):
            payload = msg.payload.decode()
            topic = msg.topic
            print(f"收到MQTT消息: topic={topic}, payload={payload}")
            for name, info in self.cfg.items():
                if name.startswith("_"):
                    continue
                if info.get("bafy_topic") == topic or topic == global_topic:
                    item_type = info.get("type", "").strip().lower()
                    # 关机项收到"off"才执行，其他项收到"on"才执行
                    if name == "关机" and payload == "off":
                        print(f"MQTT触发关机启动项: {name}")
                        self.run_item(name)
                    elif item_type in ["brightness", "value", "number"]:
                        try:
                            value = None
                            if payload.startswith("on#"):
                                value = int(payload.split("#")[1])
                            elif payload.isdigit():
                                value = int(payload)
                            if value is not None:
                                print(f"MQTT触发亮度设置: {info['cmd']}，目标亮度: {value}")
                                self.run_item(name, brightness_value=value)
                        except Exception as e:
                            print("亮度指令处理失败:", e)
                    elif name != "关机" and payload == "on":
                        print(f"MQTT触发启动项: {name}")
                        self.run_item(name)
                    break

        # 启动MQTT客户端线程
        def mqtt_thread():
            client = mqtt.Client(client_id=uid)
            client.on_connect = on_connect
            client.on_message = on_message
            try:
                client.connect("bemfa.com", 9501, 60)
                client.loop_forever()
            except Exception as e:
                print("MQTT连接失败:", e)

        t = threading.Thread(target=mqtt_thread, daemon=True)
        t.start()

import subprocess
import re

def is_screen_on():
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "display"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",      # 强制用utf-8解码
            errors="ignore"        # 忽略无法解码的字符
        )
        if result.returncode != 0:
            return None
        match = re.search(r'mState=(ON|OFF)', result.stdout)
        if not match:
            return None
        state = match.group(1)
        return state == "ON"
    except Exception:
        return None

def show_error_message(self, title, msg):
    QTimer.singleShot(0, lambda: QMessageBox.critical(self, title, msg))

# ---------------- 启动 ----------------
if __name__ == "__main__":
    # 应用程序入口 
    app = QApplication(sys.argv)
    win = Launcher()
    # 判断命令行参数
    if "-help" in sys.argv:
        win.hide()  # 直接隐藏窗口，仅托盘后台运行
    else:
        win.show()
    sys.exit(app.exec_())