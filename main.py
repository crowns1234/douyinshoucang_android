"""拾光 · Android 版
抖音收藏每日摘要 — Kivy 触屏 UI
"""
import os, sys, json, threading

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.animation import Animation

# 配色
BLUE = (0.118, 0.471, 0.784, 1)     # #1e78c8
BLUE_DARK = (0.09, 0.40, 0.69, 1)
WHITE = (1, 1, 1, 1)
LIGHT_BG = (0.96, 0.96, 0.97, 1)
DARK_TEXT = (0.2, 0.2, 0.22, 1)
GRAY = (0.55, 0.55, 0.57, 1)
GREEN = (0.16, 0.65, 0.27, 1)
RED = (0.88, 0.22, 0.22, 1)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "baidu_api_key": "", "baidu_secret_key": "",
        "zhipu_api_key": "", "sender": "", "password": "",
        "receiver": "", "headless": True,
    }


def _save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class StyledButton(Button):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.background_normal = ""
        self.background_color = BLUE
        self.color = WHITE
        self.font_size = dp(16)
        self.size_hint_y = None
        self.height = dp(50)
        self.border = (0, 0, 0, 0)
        self.radius = [dp(10)]


class ConfigScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.name = "config"
        self.method_email = True  # default

        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        root.add_widget(Label(text="[b]配置[/b]", markup=True, color=DARK_TEXT,
                               size_hint_y=None, height=dp(36), font_size=dp(20)))

        scroll = ScrollView()
        form = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))
        self.fields = {}
        cfg = _load_config()

        # -- 转写 / 摘要密钥 --
        form.add_widget(self._section("转写 / 摘要密钥"))
        for key, label, secret in [
            ("baidu_api_key", "百度 API Key", True),
            ("baidu_secret_key", "百度 Secret Key", True),
            ("zhipu_api_key", "智谱 API Key", True),
        ]:
            form.add_widget(self._field(label, cfg.get(key, ""), secret, key))

        # -- 推送方式 --
        form.add_widget(self._section("推送方式"))
        method_row = BoxLayout(orientation="horizontal", spacing=dp(6), size_hint_y=None, height=dp(40))
        self.btn_email = ToggleButton(text="邮件", group="method", state="down", size_hint_x=1)
        self.btn_wecom = ToggleButton(text="企业微信", group="method", size_hint_x=1)
        self.btn_email.bind(on_press=self._toggle_method)
        self.btn_wecom.bind(on_press=self._toggle_method)
        method_row.add_widget(self.btn_email)
        method_row.add_widget(self.btn_wecom)
        form.add_widget(method_row)

        # 邮件字段组
        self.email_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None, height=dp(190))
        for key, label, secret in [
            ("sender", "发件邮箱", False), ("password", "邮箱授权码", True), ("receiver", "收件邮箱", False),
        ]:
            self.email_box.add_widget(self._field(label, cfg.get(key, ""), secret, key, short=True))
        form.add_widget(self.email_box)

        # 企业微信字段组
        self.wecom_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None, height=dp(50))
        self.wecom_box.add_widget(self._field("Webhook", cfg.get("webhook", ""), False, "webhook", short=True))
        form.add_widget(self.wecom_box)

        # -- Cookie 管理 --
        form.add_widget(self._section("Cookie 管理"))
        self.cookie_label = Label(text="检测中...", color=GRAY, font_size=dp(12),
                                   size_hint_y=None, height=dp(20), halign="left")
        form.add_widget(self.cookie_label)
        cook_btns = BoxLayout(orientation="horizontal", spacing=dp(6), size_hint_y=None, height=dp(42))
        import_btn = Button(text="导入文件", font_size=dp(13), background_color=BLUE, background_normal="", color=WHITE)
        import_btn.bind(on_press=self._import_cookie)
        paste_btn = Button(text="粘贴 JSON", font_size=dp(13), background_color=BLUE_DARK, background_normal="", color=WHITE)
        paste_btn.bind(on_press=self._paste_cookie)
        cook_btns.add_widget(import_btn)
        cook_btns.add_widget(paste_btn)
        form.add_widget(cook_btns)

        # -- 定时任务 --
        form.add_widget(self._section("每天自动运行"))
        sched_row = BoxLayout(orientation="horizontal", spacing=dp(6), size_hint_y=None, height=dp(44))
        sched_row.add_widget(Label(text="时间", color=DARK_TEXT, size_hint_x=None, width=dp(40)))
        self.sched_hour = TextInput(text=str(cfg.get("sched_hour", 23)), multiline=False,
                                     size_hint_x=0.3, height=dp(40), font_size=dp(16),
                                     background_color=WHITE, foreground_color=DARK_TEXT,
                                     halign="center", padding=[dp(4), dp(8)])
        self.sched_min = TextInput(text=str(cfg.get("sched_min", 0)), multiline=False,
                                    size_hint_x=0.3, height=dp(40), font_size=dp(16),
                                    background_color=WHITE, foreground_color=DARK_TEXT,
                                    halign="center", padding=[dp(4), dp(8)])
        sched_row.add_widget(self.sched_hour)
        sched_row.add_widget(Label(text=":", color=DARK_TEXT, size_hint_x=None, width=dp(8)))
        sched_row.add_widget(self.sched_min)
        sched_row.add_widget(Label(text="（平台任务/提醒）", color=GRAY, font_size=dp(11)))
        form.add_widget(sched_row)

        # -- 保存 --
        save_btn = StyledButton(text="保 存 配 置", size_hint_y=None, height=dp(50))
        save_btn.bind(on_press=self._save)
        form.add_widget(save_btn)

        # 底部留白
        form.add_widget(BoxLayout(size_hint_y=None, height=dp(20)))

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _section(self, title: str) -> Label:
        return Label(text=f"[b]{title}[/b]", markup=True, color=BLUE,
                     size_hint_y=None, height=dp(28), font_size=dp(14), halign="left")

    def _field(self, label: str, value: str, secret: bool, key: str, short: bool = False) -> BoxLayout:
        row = BoxLayout(orientation="vertical", size_hint_y=None,
                        height=dp(60) if short else dp(70), spacing=dp(1))
        row.add_widget(Label(text=label, color=GRAY, font_size=dp(11),
                             size_hint_y=None, height=dp(18), halign="left"))
        inp = TextInput(
            text=value, password=secret, multiline=False,
            background_color=WHITE, foreground_color=DARK_TEXT,
            size_hint_y=None, height=dp(40),
            padding=[dp(10), dp(10)], cursor_color=BLUE, font_size=dp(14),
        )
        row.add_widget(inp)
        self.fields[key] = inp
        return row

    def _toggle_method(self, *a):
        is_email = self.btn_email.state == "down"
        self.email_box.height = dp(180) if is_email else 0
        self.email_box.opacity = 1 if is_email else 0
        self.wecom_box.height = dp(50) if not is_email else 0
        self.wecom_box.opacity = 0 if is_email else 1
        self.method_email = is_email

    def _save(self, *a):
        cfg = {k: v.text for k, v in self.fields.items()}
        cfg["method"] = "email" if self.method_email else "wecom"
        try:
            cfg["sched_hour"] = int(self.sched_hour.text)
            cfg["sched_min"] = int(self.sched_min.text)
        except ValueError:
            cfg["sched_hour"], cfg["sched_min"] = 23, 0
        _save_config(cfg)
        self._schedule_notify(cfg["sched_hour"], cfg["sched_min"])
        popup = Popup(title="保存成功", content=Label(text="配置已保存"), size_hint=(0.6, 0.25))
        popup.open()

    def _schedule_notify(self, h, m):
        """设置每日通知提醒（需 App 前台或配合 Tasker）。"""
        try:
            from plyer import notification
            notification.notify(
                title="拾光提醒",
                message=f"每日 {h:02d}:{m:02d} 会提醒你生成摘要\n（需保持 App 运行或使用 Tasker）",
                app_name="拾光",
                timeout=5,
            )
        except Exception:
            pass

    def on_enter(self):
        self._check_cookie()

    def _check_cookie(self):
        cook_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", "douyin_cookies.json")
        if os.path.exists(cook_path):
            self.cookie_label.text = "Cookie: 已就绪"
            self.cookie_label.color = GREEN
        else:
            self.cookie_label.text = "Cookie: 未找到"
            self.cookie_label.color = RED

    def _import_cookie(self, *a):
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.boxlayout import BoxLayout
        box = BoxLayout(orientation="vertical", spacing=dp(8))
        fc = FileChooserListView()
        box.add_widget(fc)
        btn = Button(text="打开", size_hint_y=None, height=dp(44))
        box.add_widget(btn)
        popup = Popup(title="选择 JSON", content=box, size_hint=(0.9, 0.7))
        def on_open(*a):
            sel = fc.selection
            if sel:
                try:
                    import shutil
                    os.makedirs(os.path.dirname(self._cook_path()), exist_ok=True)
                    shutil.copy(sel[0], self._cook_path())
                    self._check_cookie()
                    popup.dismiss()
                except Exception as e:
                    self.cookie_label.text = f"导入失败: {e}"
                    self.cookie_label.color = RED
        btn.bind(on_press=on_open)
        popup.open()

    def _paste_cookie(self, *a):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        ti = TextInput(multiline=True, hint_text="粘贴 JSON ...", font_size=dp(13),
                       background_color=WHITE, foreground_color=DARK_TEXT)
        box.add_widget(ti)
        btn = Button(text="保存", size_hint_y=None, height=dp(44), background_color=BLUE, background_normal="", color=WHITE)
        box.add_widget(btn)
        popup = Popup(title="粘贴 Cookie", content=box, size_hint=(0.9, 0.7))
        def on_save(*a):
            text = ti.text.strip()
            if text:
                try:
                    json.loads(text)
                    os.makedirs(os.path.dirname(self._cook_path()), exist_ok=True)
                    with open(self._cook_path(), "w", encoding="utf-8") as f:
                        f.write(text)
                    self._check_cookie()
                    popup.dismiss()
                except Exception as e:
                    self.cookie_label.text = f"JSON 无效: {e}"
                    self.cookie_label.color = RED
        btn.bind(on_press=on_save)
        popup.open()

    def _cook_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", "douyin_cookies.json")


class RunScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.name = "run"

        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        root.add_widget(Label(text="[b]生成摘要[/b]", markup=True, color=DARK_TEXT,
                               size_hint_y=None, height=dp(40), font_size=dp(20)))

        self.status = Label(text="就绪", color=GRAY, size_hint_y=None, height=dp(30))
        root.add_widget(self.status)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        root.add_widget(self.progress)

        run_btn = StyledButton(text="一键生成摘要", size_hint_y=None, height=dp(56), font_size=dp(18))
        run_btn.bind(on_press=self._run)
        root.add_widget(run_btn)

        log_label = Label(text="运行日志", color=GRAY, font_size=dp(12),
                          size_hint_y=None, height=dp(24), halign="left")
        root.add_widget(log_label)

        self.log_box = Label(text="", color=DARK_TEXT, font_size=dp(13),
                             size_hint_y=None, height=dp(200), valign="top", halign="left")
        self.log_box.bind(texture_size=self.log_box.setter("size"))
        log_scroll = ScrollView()
        log_scroll.add_widget(self.log_box)
        root.add_widget(log_scroll)

        self.add_widget(root)

    def _run(self, *a):
        self.status.text = "收集中..."
        self.progress.value = 10
        self._log("开始采集抖音收藏...")
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _log(self, msg: str):
        self.log_box.text = self.log_box.text + msg + "\n"

    def _pipeline(self):
        try:
            from src.collector_http import collect_http
            from src.config import load_config
            from src.pipeline import run_pipeline

            cfg = load_yaml_cfg()
            Clock.schedule_once(lambda dt: setattr(self.progress, 'value', 30), 0)
            Clock.schedule_once(lambda dt: self._log("正在转写 + 摘要..."), 0)

            items = collect_http(cfg)
            if not items:
                Clock.schedule_once(lambda dt: self._log("今日无新增收藏"), 0)
                return

            Clock.schedule_once(lambda dt: setattr(self.progress, 'value', 60), 0)
            result = run_pipeline(cfg)

            Clock.schedule_once(lambda dt: setattr(self.progress, 'value', 100), 0)
            n = len(result.get("items") or [])
            pushed = result.get("pushed", False)
            Clock.schedule_once(
                lambda dt: self._log(f"完成！{n} 条 | 推送: {'已发送' if pushed else '仅本地'}"),
                0,
            )
        except Exception as e:
            Clock.schedule_once(lambda dt: self._log(f"错误: {e}"), 0)


class ResultScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.name = "result"

        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        root.add_widget(Label(text="[b]日报历史[/b]", markup=True, color=DARK_TEXT,
                               size_hint_y=None, height=dp(36), font_size=dp(20)))

        self.date_selector = Spinner(
            text="选择日期", values=["选择日期"],
            background_color=WHITE, color=DARK_TEXT,
            size_hint_y=None, height=dp(44), font_size=dp(14),
        )
        self.date_selector.bind(text=self._on_date)
        root.add_widget(self.date_selector)

        self.preview = Label(text="暂无日报", color=GRAY, font_size=dp(13),
                             size_hint_y=None, valign="top", halign="left")
        self.preview.bind(texture_size=self.preview.setter("size"))
        scroll = ScrollView()
        scroll.add_widget(self.preview)
        root.add_widget(scroll)

        self.add_widget(root)

    def on_enter(self):
        self._refresh_dates()

    def _refresh_dates(self):
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        dates = []
        if os.path.isdir(out):
            dates = sorted(
                [f.replace("digest_", "").replace(".md", "")
                 for f in os.listdir(out) if f.startswith("digest_") and f.endswith(".md")],
                reverse=True,
            )
        if dates:
            self.date_selector.values = dates
            self.date_selector.text = dates[0]
        else:
            self.date_selector.values = ["暂无数据"]

    def _on_date(self, spinner, text):
        if text in ("选择日期", "暂无数据"):
            self.preview.text = "暂无日报"
            return
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "output", f"digest_{text}.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.preview.text = f.read()[:5000]
        except Exception:
            self.preview.text = "无法加载"


class BottomNav(BoxLayout):
    def __init__(self, screen_manager: ScreenManager, **kw):
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self.sm = screen_manager
        self.buttons = []

        for name, label in [("config", "配置"), ("run", "运行"), ("result", "结果")]:
            btn = Button(
                text=label, color=WHITE, font_size=dp(14),
                background_normal="", background_color=BLUE,
                size_hint_x=1, radius=[0],
            )
            btn.bind(on_press=self._make_switch(name))
            self.add_widget(btn)
            self.buttons.append((btn, name))

    def _make_switch(self, name):
        def switch(*a):
            self.sm.current = name
        return switch


class ShiGuangApp(App):
    def build(self):
        Window.clearcolor = LIGHT_BG[:3] + (1,)
        sm = ScreenManager()
        sm.add_widget(ConfigScreen())
        sm.add_widget(RunScreen())
        sm.add_widget(ResultScreen())

        root = BoxLayout(orientation="vertical")
        root.add_widget(sm)
        root.add_widget(BottomNav(sm))
        return root


if __name__ == "__main__":
    ShiGuangApp().run()
