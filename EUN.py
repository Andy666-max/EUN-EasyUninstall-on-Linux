#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf, GLib
import apt
import subprocess
import os
import re
import cairo
import math
import threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf, Gdk
#--桌面图标修复---
app = Gtk.Application(application_id='io.github.andy.EasyUninstall')
# 0.生成空白占位符
def create_gear_pixbuf(size):
    """生成一个黑色齿轮图标的 Pixbuf，尺寸 size x size"""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)

    # 黑色填充
    cr.set_source_rgba(0.5, 0.5, 0.5, 1)

    # 中心圆半径
    inner_radius = size * 0.28
    outer_radius = size * 0.48
    cx, cy = size / 2, size / 2

    # 画中心圆
    cr.arc(cx, cy, inner_radius, 0, 2 * math.pi)
    cr.fill()

    # 画 8 个齿
    num_teeth = 8
    tooth_width = size * 0.15
    for i in range(num_teeth):
        angle = i * (2 * math.pi / num_teeth) - math.pi / 2
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(angle)
        cr.rectangle(-tooth_width / 2, inner_radius - 1,
                     tooth_width, outer_radius - inner_radius + 1)
        cr.fill()
        cr.restore()

    # 从 surface 创建 Pixbuf
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
# ------------------------------------------------------------
# 1. 图标映射器（支持多目录 + 绝对路径图标）
# ------------------------------------------------------------
def build_pkg_icon_map(icon_size=30, batch_size=200):
    """
    批量反查 .desktop 文件所属包，大幅加速启动。
    支持多目录、绝对路径图标。
    """
    pkg_icons = {}
    desktop_dirs = [
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/opt/apps/com.qq.weixin/entries/applications",
    ]

    # 第一步：收集所有 .desktop 文件路径
    desktop_files = []
    for apps_dir in desktop_dirs:
        if not os.path.isdir(apps_dir):
            continue
        for fname in os.listdir(apps_dir):
            if fname.endswith(".desktop"):
                desktop_files.append(os.path.join(apps_dir, fname))

    if not desktop_files:
        return pkg_icons

    # 第二步：分批执行 dpkg -S，构建 路径→包名 字典
    file_to_pkg = {}
    for i in range(0, len(desktop_files), batch_size):
        batch = desktop_files[i:i + batch_size]
        try:
            # 将路径作为参数传给 dpkg -S，多个路径用空格分隔
            result = subprocess.run(
                ['dpkg', '-S'] + batch,
                capture_output=True, text=True
            )
            # dpkg -S 多文件时，输出可能是多行，每行格式："包名: 路径"
            for line in result.stdout.strip().split('\n'):
                if ':' not in line:
                    continue
                # 注意：路径中可能包含冒号（如 "package: /path:with:colon"）
                # 更稳健的做法是用 split(':', 1)，但路径中如果包含冒号会截断
                # dpkg -S 输出格式为 "包名: 文件路径"，文件路径不会包含换行符，
                # 但可能包含空格，这里简单以第一个冒号分隔
                pkg, path = line.split(':', 1)
                file_to_pkg[path.strip()] = pkg.strip()
        except Exception:
            # 如果某批出错（比如路径都不属于任何包），继续下一批
            continue

    # 第三步：重新遍历 .desktop 文件，加载图标
    icon_theme = Gtk.IconTheme.get_default()
    for path in desktop_files:
        pkg_name = file_to_pkg.get(path)
        if not pkg_name or pkg_name in pkg_icons:
            continue

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            match = re.search(r'^Icon\s*=\s*(.+)$', content, re.MULTILINE)
            if not match:
                continue
            icon_value = match.group(1).strip()
            if not icon_value:
                continue
        except Exception:
            continue

        # 加载图标（同之前的逻辑）
        pixbuf = None
        if os.path.isabs(icon_value):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
                    icon_value, icon_size, icon_size)
            except Exception:
                pass
        if not pixbuf:
            try:
                pixbuf = icon_theme.load_icon(icon_value, icon_size,
                                              Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
        if not pixbuf:
            try:
                hicolor = Gtk.IconTheme.new()
                hicolor.set_custom_theme("hicolor")
                pixbuf = hicolor.load_icon(icon_value, icon_size,
                                           Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
        if pixbuf:
            pkg_icons[pkg_name] = pixbuf

    return pkg_icons

# ------------------------------------------------------------
# 2. 主窗口（默认只显示有图标软件，“显示全部软件”复选框）
# ------------------------------------------------------------
class PkgIconWindow(Gtk.ApplicationWindow):
    def __init__(self,application):
        super().__init__(application=application,title="轻松卸载")
        self.set_default_size(800, 600)
        self.set_border_width(10)

        # 图标映射
        self.statusbar = Gtk.Statusbar()
        self.statusbar.push(0, "正在扫描桌面图标...")
        self.icon_size = 30                           # 当前使用的图标大小
        self.default_icon = create_gear_pixbuf(self.icon_size)
        self.pkg_icons = build_pkg_icon_map(icon_size=self.icon_size)
        self.statusbar.push(0, f"准备就绪，共 {len(self.pkg_icons)} 个包有图标")

        # 主布局
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)

        # ---- 搜索栏与“显示全部软件”复选框 ----
        search_box = Gtk.Box(spacing=6)
        lbl = Gtk.Label(label="搜索：")
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.connect("search-changed", self.on_search_changed)
        search_box.pack_start(lbl, False, False, 0)
        search_box.pack_start(self.search_entry, True, True, 0)

        # ★ 复选框：默认不勾选（只显示有图标），勾选后显示全部软件
        self.show_all_btn = Gtk.CheckButton(label="显示全部软件")
        self.show_all_btn.set_active(False)          # 初始不勾选，即“只显示有图标”
        self.show_all_btn.connect("toggled", self.on_show_all_toggled)
        search_box.pack_start(self.show_all_btn, False, False, 0)
        vbox.pack_start(search_box, False, False, 0)

        # 滚动窗口 + TreeView
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        vbox.pack_start(scrolled, True, True, 0)

        # 模型：图标(Pixbuf), 包名, 版本, 描述
        self.model = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str)
        self.filter_model = self.model.filter_new()
        self.filter_model.set_visible_func(self.filter_func)
        self.treeview = Gtk.TreeView(model=self.filter_model)
        scrolled.add(self.treeview)

        # 图标列
        renderer_pixbuf = Gtk.CellRendererPixbuf()
        col_icon = Gtk.TreeViewColumn("", renderer_pixbuf)
        col_icon.set_fixed_width(self.icon_size + 6)   # 列宽 36，留边距
        col_icon.set_cell_data_func(renderer_pixbuf, self.icon_data_func, None) 
        self.treeview.append_column(col_icon)

        # 包名列
        renderer_text = Gtk.CellRendererText()
        col_name = Gtk.TreeViewColumn("软件包", renderer_text, text=1)
        col_name.set_resizable(True)
        col_name.set_min_width(150)
        self.treeview.append_column(col_name)

        # 版本列
        col_ver = Gtk.TreeViewColumn("版本", Gtk.CellRendererText(), text=2)
        col_ver.set_resizable(True)
        self.treeview.append_column(col_ver)

        # 描述列
        col_desc = Gtk.TreeViewColumn("描述", Gtk.CellRendererText(), text=3)
        col_desc.set_resizable(True)
        self.treeview.append_column(col_desc)

        # 右键菜单
        self.treeview.connect("button-press-event", self.on_button_press)
        self.popup_menu = Gtk.Menu()
        item_uninstall = Gtk.MenuItem(label="卸载此软件包")
        item_uninstall.connect("activate", self.on_uninstall)
        self.popup_menu.append(item_uninstall)
        self.popup_menu.show_all()
        # ---- 底部盒子：状态栏（左） + 清除多余软件包按钮（右） ----
        self.bottom_box = Gtk.Box(spacing=6)

        # 状态栏占据所有可用空间，放在左边
        self.statusbar = Gtk.Statusbar()
        self.bottom_box.pack_start(self.statusbar, True, True, 0)

        # “清除多余软件包”按钮，放在右边
        self.autoremove_btn = Gtk.Button(label="清除多余软件包")
        self.autoremove_btn.connect("clicked", self.on_autoremove_clicked)
        self.bottom_box.pack_end(self.autoremove_btn, False, False, 0)

        # 将底部盒子添加到窗口最底部
        vbox.pack_end(self.bottom_box, False, False, 0)

       
        # 填充数据（此时 filter_func 已经生效，默认只显示有图标的包）
        self.populate_model()
    def icon_data_func(self, column, cell, model, iter, data):
        pixbuf = model.get_value(iter, 0)
        if pixbuf is None:
            cell.set_property('pixbuf', self.default_icon)
        else:
            cell.set_property('pixbuf', pixbuf)
    # --- 填充包列表 ---
    def populate_model(self):
        cache = apt.Cache()
        count = 0
        for pkg in cache:
            if pkg.installed:
                icon = self.pkg_icons.get(pkg.name, None)
                version = pkg.installed.version
                desc = pkg.installed.summary or ""
                self.model.append([icon, pkg.name, version, desc])
                count += 1
        self.statusbar.push(0, f"已加载 {count} 个已安装包")

    # --- 过滤函数（优先满足“只显示有图标”，除非勾选“显示全部”） ---
    def filter_func(self, model, iter, data):
        # 1. 搜索条件
        text = self.search_entry.get_text().strip().lower()
        if text:
            pkg_name = model.get_value(iter, 1).lower()
            if text not in pkg_name:
                return False

        # 2. 如果“显示全部”按钮未激活，则只显示有图标的包
        if not self.show_all_btn.get_active():
            pixbuf = model.get_value(iter, 0)
            if pixbuf is None:
                return False

        return True

    def on_search_changed(self, entry):
        self.filter_model.refilter()

    def on_show_all_toggled(self, button):
        self.filter_model.refilter()

    # --- 右键菜单 ---
    def on_button_press(self, widget, event):
        if event.button == 3:
            path = self.treeview.get_path_at_pos(int(event.x), int(event.y))
            if path:
                self.treeview.grab_focus()
                self.treeview.set_cursor(path[0])
                self.popup_menu.popup_at_pointer(event)
                return True
        return False

    # --- 卸载功能 ---
    def on_uninstall(self, menuitem):
        """用户点击卸载，确认后直接进入卸载流程（只一次密码弹窗）"""
        model, treeiter = self.treeview.get_selection().get_selected()
        if not treeiter:
            return
        child_iter = self.filter_model.convert_iter_to_child_iter(treeiter)
        pkg_name = self.model.get_value(child_iter, 1)

        # 确认对话框
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"确定要卸载软件包 “{pkg_name}” 吗？"
        )
        dialog.format_secondary_text("这会使用 apt purge 彻底移除该软件包及其配置文件。")
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        # 立即显示“正在卸载”等待框，并提示用户需要输入密码
        self._show_uninstall_wait_dialog(pkg_name)
        # 在后台线程执行卸载（只一次 pkexec）
        self.statusbar.push(0, f"正在卸载 {pkg_name} ...")
        threading.Thread(target=self._uninstall_package, args=(pkg_name, child_iter), daemon=True).start()

    def _show_uninstall_wait_dialog(self, pkg_name):
        """显示不可关闭的等待框，提示用户输入密码"""
        self._wait_dialog = Gtk.Dialog(
            title="卸载中",
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            buttons=()   # 无按钮，不能手动关闭
        )
        box = self._wait_dialog.get_content_area()
        spinner = Gtk.Spinner()
        spinner.start()
        label = Gtk.Label(label=f"正在卸载 {pkg_name}")
        label.set_margin_start(10)
        box.pack_start(spinner, False, False, 10)
        box.pack_start(label, False, False, 10)
        self._wait_dialog.show_all()

    def _uninstall_package(self, pkg_name, child_iter):
        """后台执行卸载（唯一一次 pkexec）"""
        try:
            subprocess.run(
                ['pkexec', 'apt-get', 'purge', '-y', pkg_name],
                check=True,
                capture_output=True,
                text=True
            )
            success = True
            error_msg = None
        except subprocess.CalledProcessError as e:
            success = False
            error_msg = f"卸载失败：{e.stderr or e}"
        except Exception as e:
            success = False
            error_msg = f"错误：{e}"

        # 卸载完成后的 UI 更新
        GLib.idle_add(lambda: self._on_uninstall_finished(pkg_name, success, error_msg, child_iter))

    def _on_uninstall_finished(self, pkg_name, success, error_msg, child_iter):
        """卸载结束后的清理"""
        # 关闭等待对话框
        if hasattr(self, '_wait_dialog') and self._wait_dialog:
            self._wait_dialog.destroy()
            self._wait_dialog = None

        if success:
            self.model.remove(child_iter)
            self.statusbar.push(0, f"已成功卸载 {pkg_name}")
        else:
            self.statusbar.push(0, error_msg)
    #-----自动清除软件包--------
    def on_autoremove_clicked(self, button):
        """确认后立即显示等待框，后台执行一次 pkexec apt autoremove"""
        # 防重复点击
        button.set_sensitive(False)

        # 确认对话框
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="确定要清除多余软件包吗？"
        )
        dialog.format_secondary_text("这会运行 ‘apt autoremove’，卸载所有不再需要的依赖包。")
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            button.set_sensitive(True)
            return

        # 显示“正在清理”等待框（密码框出现前）
        self._show_autoremove_wait_dialog()
        self.statusbar.push(0, "正在清除多余软件包，请在弹出的认证窗口中输入密码...")

        # 后台线程执行清理
        threading.Thread(target=self._run_autoremove, daemon=True).start()

    def _show_autoremove_wait_dialog(self):
        """创建不可关闭的“正在清理”对话框"""
        self._autoremove_wait_dialog = Gtk.Dialog(
            title="清理中",
            parent=self,
            flags=Gtk.DialogFlags.MODAL,
            buttons=()   # 没有按钮，用户无法手动关闭
        )
        box = self._autoremove_wait_dialog.get_content_area()
        spinner = Gtk.Spinner()
        spinner.start()
        label = Gtk.Label(label="正在清除多余软件包，请在弹出的认证窗口中输入密码...")
        label.set_margin_start(10)
        box.pack_start(spinner, False, False, 10)
        box.pack_start(label, False, False, 10)
        self._autoremove_wait_dialog.show_all()

    def _run_autoremove(self):
        """后台执行 autoremove（只调一次 pkexec）"""
        try:
            subprocess.run(
                ['pkexec', 'apt', 'autoremove', '-y'],
                check=True,
                capture_output=True,
                text=True
            )
            success = True
            error_msg = None
        except subprocess.CalledProcessError as e:
            success = False
            error_msg = f"清理失败：{e.stderr or e}"
        except Exception as e:
            success = False
            error_msg = f"发生错误：{e}"

        # 回到主线程完成 UI 更新
        GLib.idle_add(lambda: self._on_autoremove_finished(success, error_msg))

    def _on_autoremove_finished(self, success, error_msg):
        """清理完成后的界面更新"""
        # 关闭等待对话框
        if hasattr(self, '_autoremove_wait_dialog') and self._autoremove_wait_dialog:
            self._autoremove_wait_dialog.destroy()
            self._autoremove_wait_dialog = None

        # 重新启用按钮
        self.autoremove_btn.set_sensitive(True)

        if success:
            # 刷新列表
            self.model.clear()
            self.populate_model()
            self.search_entry.set_text('')
            self.filter_model.refilter()
            self.statusbar.push(0, "多余软件包清除完成，列表已刷新")
        else:
            self.statusbar.push(0, error_msg or "清理过程中出现未知错误")
#--桌面图标修补后半部--
#---------程序入口--------------
def on_activate(app):
    win = PkgIconWindow(app)
    win.show_all()
if __name__ == "__main__":
    app.connect('activate',on_activate)
    app.run(None)
