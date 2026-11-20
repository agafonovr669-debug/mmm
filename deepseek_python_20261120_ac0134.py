import tkinter as tk
from tkinter import ttk, messagebox
import os, sys, json, ctypes, subprocess, platform, datetime, winreg, threading
try:
    import psutil
except Exception:
    psutil = None

APP_NAME = "Game Optimizer PRO"
BASE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GameOptimizerPRO")
BACKUP_DIR = os.path.join(BASE, "backups")
LOG_FILE = os.path.join(BASE, "app.log")
os.makedirs(BACKUP_DIR, exist_ok=True)

REG_ITEMS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1, winreg.REG_DWORD),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, winreg.REG_DWORD),
    (winreg.HKEY_CURRENT_USER, r"System\GameConfigStore", "GameDVR_Enabled", 0, winreg.REG_DWORD),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, winreg.REG_DWORD),
]


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def read_value(root, path, name):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, name)
            return {"exists": True, "value": value, "kind": kind}
    except FileNotFoundError:
        return {"exists": False}
    except OSError:
        return {"exists": False}


def write_value(root, path, name, value, kind):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, kind, value)


def backup_state():
    snapshot = {"created": datetime.datetime.now().isoformat(),
                "rolled_back": False,
                "registry": []}
    for root, path, name, value, kind in REG_ITEMS:
        old = read_value(root, path, name)
        snapshot["registry"].append({
            "root": "HKCU", "path": path, "name": name,
            "old": old, "new": value, "kind": kind
        })
    path = os.path.join(BACKUP_DIR, "backup_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return path


def apply_profile():
    """Возвращает (backup_path, changed_list, failed_list, notes_list)."""
    backup = backup_state()
    changed, failed, notes = [], [], []
    for root, path, name, value, kind in REG_ITEMS:
        try:
            existed = read_value(root, path, name).get("exists", False)
            write_value(root, path, name, value, kind)
            actual = read_value(root, path, name)
            if actual.get("exists") and actual.get("value") == value:
                changed.append((f"{path}\\{name}", "обновлён" if existed else "создан"))
                if not existed:
                    notes.append(f"Ключ создан с нуля: {path}\\{name}")
            else:
                failed.append(f"{path}\\{name}")
        except OSError as e:
            failed.append(f"{path}\\{name}: {e}")
    return backup, changed, failed, notes


def _load_backup(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_backup(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def rollback_from(path):
    """Откат из конкретного файла. Помечает бэкап как использованный."""
    data = _load_backup(path)
    if data.get("rolled_back"):
        raise RuntimeError("Этот бэкап уже был использован для отката.")
    for item in data.get("registry", []):
        p, name, old = item["path"], item["name"], item["old"]
        try:
            if old.get("exists"):
                write_value(winreg.HKEY_CURRENT_USER, p, name, old["value"], old["kind"])
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, p, 0, winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        except OSError as e:
            raise RuntimeError(f"Не удалось восстановить {p}\\{name}: {e}")
    data["rolled_back"] = True
    data["rolled_back_at"] = datetime.datetime.now().isoformat()
    _save_backup(path, data)
    return path


def list_backups():
    """Список (path, mtime, data) по убыванию свежести."""
    result = []
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith(".json"):
            continue
        full = os.path.join(BACKUP_DIR, f)
        try:
            data = _load_backup(full)
        except Exception:
            data = {"created": "?", "rolled_back": False}
        result.append((full, os.path.getmtime(full), data))
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def current_registry_state():
    """Список (path\\name, exists, value) для текущего состояния 4 параметров."""
    out = []
    for root, path, name, _expected, _kind in REG_ITEMS:
        cur = read_value(root, path, name)
        out.append((f"{path}\\{name}", cur.get("exists", False), cur.get("value")))
    return out


def disk_type_letter(letter="C:"):
    """HDD / SSD / Unknown для диска C: через PowerShell."""
    try:
        cmd = ("Get-PhysicalDisk | Where-Object { $_.DeviceID -eq 0 } | "
               "Select-Object -ExpandProperty MediaType")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=6)
        t = (r.stdout or "").strip()
        if t:
            return t
    except Exception:
        pass
    return "Unknown"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x760")
        self.minsize(860, 660)
        self.configure(bg="#10151e")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#10151e")
        self.style.configure("Card.TFrame", background="#1a2330")
        self.style.configure("TLabel", background="#10151e", foreground="#e8eef7", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground="#ffffff")
        self.style.configure("Sub.TLabel", foreground="#aab8ca")
        self.style.configure("TButton", font=("Segoe UI Semibold", 10), padding=10)
        self.style.configure("Accent.TButton", background="#168653", foreground="white")
        self.style.map("Accent.TButton", background=[("active", "#1ca567")])
        self._monitor_busy = False
        self.build_ui()
        self.refresh_status()

    def build_ui(self):
        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer); top.pack(fill="x")
        ttk.Label(top, text="GAME OPTIMIZER PRO", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="WINDOWS 11  •  SAFE PROFILE", style="Sub.TLabel").pack(side="right")
        ttk.Label(outer, text="Максимум производительности без рискованных твиков и потери плавности",
                  style="Sub.TLabel").pack(anchor="w", pady=(5, 18))

        specs = ttk.Frame(outer); specs.pack(fill="x", pady=(0, 14))
        for title, value in [("CPU", "Intel Core i5-12400F"), ("GPU", "NVIDIA RTX 3060 Ti"),
                             ("RAM", "16 GB DDR4 • 2×8"), ("DISPLAY", "1920×1080 • 144 Hz"), ("DRIVE", "HDD")]:
            card = ttk.Frame(specs, style="Card.TFrame", padding=12)
            card.pack(side="left", fill="both", expand=True, padx=3)
            tk.Label(card, text=title, bg="#1a2330", fg="#93a6bd", font=("Segoe UI", 8, "bold")).pack(anchor="w")
            tk.Label(card, text=value, bg="#1a2330", fg="#ffffff", font=("Segoe UI", 9, "bold"),
                     wraplength=135).pack(anchor="w", pady=(5, 0))

        body = ttk.Frame(outer); body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Card.TFrame", padding=18); left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ttk.Frame(body, style="Card.TFrame", padding=18); right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        tk.Label(left, text="БЕЗОПАСНЫЙ ИГРОВОЙ ПРОФИЛЬ", bg="#1a2330", fg="#ffffff",
                 font=("Segoe UI Semibold", 13)).pack(anchor="w")
        desc = ("Программа включает Game Mode и отключает фоновую запись игрового процесса "
                "для текущего пользователя. Перед изменениями создаётся резервная копия реестра.")
        tk.Label(left, text=desc, bg="#1a2330", fg="#b8c5d6", wraplength=380, justify="left").pack(anchor="w", pady=12)
        ttk.Button(left, text="СОЗДАТЬ РЕЗЕРВНУЮ КОПИЮ", command=self.do_backup).pack(fill="x", pady=5)
        ttk.Button(left, text="ПРИМЕНИТЬ SAFE MAX FPS", style="Accent.TButton", command=self.do_apply).pack(fill="x", pady=5)
        ttk.Button(left, text="ОТКАТИТЬ ПОСЛЕДНИЕ ИЗМЕНЕНИЯ", command=self.do_rollback).pack(fill="x", pady=5)
        ttk.Button(left, text="ВСЕ РЕЗЕРВНЫЕ КОПИИ…", command=self.show_backups).pack(fill="x", pady=5)
        ttk.Button(left, text="ОТКРЫТЬ ПАПКУ С БЭКАПАМИ", command=self.open_backup_folder).pack(fill="x", pady=5)
        ttk.Button(left, text="ОБНОВИТЬ МОНИТОРИНГ", command=self.refresh_status).pack(fill="x", pady=5)
        ttk.Button(left, text="ПРОФИЛЬ GTA V MAX FPS", command=self.show_gta_profile).pack(fill="x", pady=5)
        ttk.Button(left, text="OTHER OPTIMIZATION", command=self.show_other_optimization).pack(fill="x", pady=5)

        tk.Label(right, text="МОНИТОРИНГ", bg="#1a2330", fg="#ffffff",
                 font=("Segoe UI Semibold", 13)).pack(anchor="w")
        self.status = tk.Label(right, text="Загрузка…", bg="#1a2330", fg="#b8c5d6",
                               justify="left", font=("Segoe UI", 10))
        self.status.pack(anchor="w", pady=12)

        tk.Label(right, text="ТЕКУЩЕЕ СОСТОЯНИЕ ПАРАМЕТРОВ", bg="#1a2330", fg="#ffffff",
                 font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(6, 4))
        self.state_frame = tk.Frame(right, bg="#1a2330")
        self.state_frame.pack(fill="x", anchor="w")

        tk.Label(right, text="ИГРОВЫЕ РЕКОМЕНДАЦИИ", bg="#1a2330", fg="#ffffff",
                 font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(16, 5))
        rec = ("CS2: Reflex включить в игре; тени/эффекты снизить.\n"
               "Fortnite: Performance Mode для максимального FPS.\n"
               "GTA V: MSAA и Advanced Graphics выключить.\n\n"
               "HDD: перенос игр на SSD улучшит загрузки и подгрузку ресурсов, "
               "но не гарантирует рост среднего FPS.")
        tk.Label(right, text=rec, bg="#1a2330", fg="#b8c5d6", justify="left", wraplength=400).pack(anchor="w")

        self.log = tk.Text(outer, height=8, bg="#0b1017", fg="#cfe0f5", insertbackground="white",
                           relief="flat", font=("Consolas", 9), padx=10, pady=8)
        self.log.pack(fill="x", pady=(14, 0))
        self.write_log("Готово. Изменения применяются только после твоего подтверждения.")
        if not is_admin():
            self.write_log("Запуск без прав администратора: выбранные настройки HKCU обычно доступны без них.")

    def write_log(self, msg):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
        self.log.insert("end", line + "\n")
        self.log.see("end")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def do_backup(self):
        try:
            p = backup_state()
            self.write_log("Резервная копия создана: " + p)
            messagebox.showinfo(APP_NAME, "Резервная копия создана.")
        except Exception as e:
            self.write_log("Ошибка бэкапа: " + str(e))
            messagebox.showerror(APP_NAME, str(e))

    def do_apply(self):
        if not messagebox.askyesno(APP_NAME,
                                   "Создать резервную копию и применить безопасный игровой профиль?"):
            return
        try:
            backup, changed, failed, notes = apply_profile()
            self.write_log("Профиль применён. Backup: " + backup)
            for name, st in changed:
                self.write_log(f"  ✓ {name} ({st})")
            for n in notes:
                self.write_log("  · " + n)
            for name in failed:
                self.write_log("  ✗ " + name)
            if failed:
                messagebox.showwarning(
                    APP_NAME,
                    f"Применено: {len(changed)}\nНе удалось: {len(failed)}\n"
                    "Смотри лог. Возможно, политика группы блокирует запись."
                )
            else:
                messagebox.showinfo(
                    APP_NAME,
                    f"Профиль применён ({len(changed)} параметров).\n"
                    "Резервная копия сохранена.\n"
                    "Некоторые параметры могут вступить в силу после выхода из системы."
                )
            self.refresh_status()
        except Exception as e:
            self.write_log("Ошибка применения: " + str(e))
            messagebox.showerror(APP_NAME, str(e))

    def do_rollback(self):
        backups = list_backups()
        candidates = [b for b in backups if not b[2].get("rolled_back")]
        if not candidates:
            messagebox.showinfo(APP_NAME, "Нет доступных резервных копий для отката.")
            return
        p = candidates[0][0]
        if not messagebox.askyesno(APP_NAME, "Восстановить значения из самой свежей неиспользованной копии?"):
            return
        try:
            used = rollback_from(p)
            self.write_log("Откат выполнен из: " + used)
            messagebox.showinfo(APP_NAME, "Настройки восстановлены.")
            self.refresh_status()
        except Exception as e:
            self.write_log("Ошибка отката: " + str(e))
            messagebox.showerror(APP_NAME, str(e))

    def open_backup_folder(self):
        try:
            os.startfile(BACKUP_DIR)
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def show_backups(self):
        win = tk.Toplevel(self)
        win.title("Резервные копии")
        win.geometry("720x520")
        win.configure(bg="#10151e")
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="РЕЗЕРВНЫЕ КОПИИ", bg="#10151e", fg="#ffffff",
                 font=("Segoe UI Semibold", 16)).pack(anchor="w")
        tk.Label(frame, text="Папка: " + BACKUP_DIR, bg="#10151e", fg="#aab8ca",
                 font=("Consolas", 9)).pack(anchor="w", pady=(0, 10))

        canvas = tk.Canvas(frame, bg="#10151e", highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg="#10151e")
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw", width=660)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def render():
            for w in content.winfo_children():
                w.destroy()
            backups = list_backups()
            if not backups:
                tk.Label(content, text="Пока нет резервных копий.",
                         bg="#10151e", fg="#aab8ca").pack(anchor="w", pady=20)
                return
            for full, mtime, data in backups:
                used = data.get("rolled_back", False)
                card = tk.Frame(content, bg="#1a2330", padx=10, pady=8)
                card.pack(fill="x", pady=4)
                ts = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                label = ts + ("   [уже откачен]" if used else "")
                tk.Label(card, text=label, bg="#1a2330",
                         fg=("#e8bd57" if used else "#ffffff"),
                         font=("Segoe UI Semibold", 10)).pack(anchor="w")
                tk.Label(card, text=os.path.basename(full), bg="#1a2330",
                         fg="#91a8c2", font=("Consolas", 8)).pack(anchor="w")
                btn_row = tk.Frame(card, bg="#1a2330")
                btn_row.pack(fill="x", pady=(6, 0))
                ttk.Button(btn_row, text="ВОССТАНОВИТЬ",
                           command=lambda p=full: self._rollback_specific(p, render)).pack(side="left")
                ttk.Button(btn_row, text="ОТКРЫТЬ В БЛОКНОТЕ",
                           command=lambda p=full: self._open_in_notepad(p)).pack(side="left", padx=6)

        render()

    def _rollback_specific(self, path, after_cb):
        if not messagebox.askyesno(APP_NAME, "Восстановить значения из этой резервной копии?"):
            return
        try:
            used = rollback_from(path)
            self.write_log("Откат выполнен из: " + used)
            messagebox.showinfo(APP_NAME, "Настройки восстановлены.")
            after_cb()
            self.refresh_status()
        except Exception as e:
            self.write_log("Ошибка отката: " + str(e))
            messagebox.showerror(APP_NAME, str(e))

    def _open_in_notepad(self, path):
        try:
            subprocess.Popen(["notepad.exe", path])
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def refresh_status(self):
        if self._monitor_busy:
            return
        self._monitor_busy = True
        self.status.config(text="Обновление…")
        self._update_current_state()

        def worker():
            lines = [f"ОС: {platform.platform()}"]
            if psutil:
                try:
                    lines.append(f"CPU: {psutil.cpu_percent(interval=0.3)}%")
                    mem = psutil.virtual_memory()
                    lines.append(f"RAM: {mem.percent}% занято ({mem.used // (1024 ** 3)} / {mem.total // (1024 ** 3)} GB)")
                    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
                    lines.append(f"Системный диск: {disk.percent}% занято")
                except Exception as e:
                    lines.append("Мониторинг частично недоступен: " + str(e))
            else:
                lines.append("Мониторинг RAM/CPU: установите psutil (в EXE уже включён).")
            dtype = disk_type_letter("C:")
            lines.append(f"Тип диска C: {dtype}")
            text = "\n".join(lines)

            def apply_ui():
                self.status.config(text=text)
                self.write_log("Мониторинг обновлён.")
                self._monitor_busy = False
            self.after(0, apply_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _update_current_state(self):
        for w in self.state_frame.winfo_children():
            w.destroy()
        for full, ex, val in current_registry_state():
            if ex:
                txt = str(val)
                color = "#42c982" if txt in ("0", "1") else "#e8eef7"
            else:
                txt = "не задано"
                color = "#e8bd57"
            row = tk.Frame(self.state_frame, bg="#202d3d", padx=8, pady=5)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=os.path.basename(full), bg="#202d3d", fg="#cfe0f5",
                     font=("Consolas", 9)).pack(side="left", anchor="w")
            tk.Label(row, text=txt, bg="#202d3d", fg=color,
                     font=("Consolas", 9, "bold")).pack(side="right")

    def show_gta_profile(self):
        win = tk.Toplevel(self)
        win.title("GTA V MAX FPS — безопасный профиль")
        win.geometry("650x620")
        win.configure(bg="#10151e")
        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="GTA V MAX FPS", bg="#10151e", fg="#ffffff",
                 font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(frame, text="Рекомендованные настройки для i5-12400F + RTX 3060 Ti • 1080p",
                 bg="#10151e", fg="#aab8ca").pack(anchor="w", pady=(4, 12))
        sections = [
            ("Графика GTA V", [
                "MSAA: выключить; Reflection MSAA: выключить.",
                "Grass: Normal или High; трава Ultra часто сильно нагружает систему.",
                "Advanced Graphics: выключить для максимального FPS.",
                "Тени и отражения: Normal/High; снижать, если FPS нестабилен.",
                "Population Density / Variety: Medium; Distance Scaling: Medium.",
                "V-Sync: выключить для максимального FPS; включать ограничение FPS отдельно, если есть разрывы изображения."
            ]),
            ("Windows и NVIDIA", [
                "Windows Game Mode: включить; Game DVR/background capture: отключить, если не записываешь игру.",
                "NVIDIA: отдельный профиль GTA V; Texture Filtering Quality — High Performance.",
                "Не принуждать Low Latency Mode глобально; не дублировать Reflex там, где он недоступен.",
                "Оставить Defender, Firewall, обновления и критические службы включёнными."
            ]),
            ("HDD, RAM и плавность", [
                "Не отключать файл подкачки; оставить управление размером за Windows.",
                "Не запускать дефрагментацию во время игры; для HDD использовать штатную оптимизацию дисков по расписанию.",
                "Закрывать ненужные фоновые приложения перед запуском игры.",
                "Перенос GTA V на SSD в будущем может сократить загрузки и подгрузочные задержки, но не гарантирует прирост среднего FPS."
            ]),
            ("Что профиль НЕ меняет автоматически", [
                "Не изменяет скрытые параметры реестра из неизвестных видео-твиков.",
                "Не меняет таймеры, HPET, приоритеты системных процессов, напряжения или частоты GPU/CPU.",
                "Графические параметры игры выставляются вручную в меню GTA V."
            ])
        ]
        for heading, items in sections:
            tk.Label(frame, text=heading, bg="#1a2330", fg="#ffffff",
                     font=("Segoe UI Semibold", 11), padx=10, pady=7).pack(fill="x", pady=(8, 3))
            for item in items:
                tk.Label(frame, text="• " + item, bg="#10151e", fg="#c4d1e0",
                         justify="left", wraplength=590, anchor="w").pack(fill="x", padx=6, pady=2)
        ttk.Button(frame, text="ЗАКРЫТЬ", command=win.destroy).pack(anchor="e", pady=12)

    def show_other_optimization(self):
        win = tk.Toplevel(self)
        win.title("Other Optimization — каталог настроек")
        win.geometry("760x720")
        win.minsize(650, 560)
        win.configure(bg="#10151e")

        outer = ttk.Frame(win, padding=16)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="OTHER OPTIMIZATION", bg="#10151e", fg="#ffffff",
                 font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(outer,
                 text="Каталог сгруппирован по назначению. Здесь указано, за что отвечает каждая группа и насколько она может повлиять на FPS.",
                 bg="#10151e", fg="#aab8ca", wraplength=700, justify="left").pack(anchor="w", pady=(5, 12))

        canvas = tk.Canvas(outer, bg="#10151e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg="#10151e")
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw", width=700)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        groups = [
            ("1. FPS & CPU PERFORMANCE", "Нагрузка процессора и планирование задач.",
             "Влияет на то, сколько ресурсов остаётся игре и насколько ровно выполняются игровые потоки.",
             "Возможное влияние на FPS: низкое или ситуативное; может помочь при сильной фоновой нагрузке.",
             [
                 ("Фоновые процессы и автозагрузка", "Убирает ненужные приложения из фона и запуска Windows.", "SAFE", "Небольшой/косвенный эффект. Отключать только известные ненужные приложения."),
                 ("Приоритет игровых процессов", "Определяет очередность получения процессорного времени.", "CAUTION", "Не ставить Realtime и не менять приоритеты системных процессов: это может вызвать подвисания."),
                 ("Service Host / службы Windows", "Управляет группировкой и запуском системных служб.", "CAUTION", "Не отключать службы пакетно. Эффект на FPS обычно не гарантирован.")
             ]),
            ("2. GPU OPTIMIZATION", "Настройки видеокарты и графического планирования.",
             "Может влиять на энергопотребление GPU, задержку отображения и стабильность кадров.",
             "Возможное влияние на FPS: зависит от игры и драйвера; часто эффект небольшой.",
             [
                 ("Профиль NVIDIA для каждой игры", "Позволяет задавать настройки отдельно для CS2, Fortnite и GTA V.", "SAFE", "Предпочтительнее глобальных принудительных настроек."),
                 ("Hardware-Accelerated GPU Scheduling (HAGS)", "Переключает способ планирования GPU между Windows и видеодрайвером.", "TEST", "Результат зависит от драйвера и игры. Сравнивать в одинаковой сцене; не обещает прирост."),
                 ("GPU power states / clock gating", "Управляет состояниями энергопотребления и частот GPU.", "CAUTION", "Не применять неизвестные реестровые значения и не фиксировать частоты/напряжения.")
             ]),
            ("3. POWER & LATENCY", "Питание, энергосбережение и задержки ввода.",
             "Меняет баланс между энергопотреблением и готовностью компонентов отвечать на нагрузку.",
             "Возможное влияние на FPS: небольшое; важнее отсутствие троттлинга.",
             [
                 ("Режим питания Windows", "Выбирает баланс энергопотребления и производительности.", "SAFE", "Начать со сбалансированного режима; сравнить режим высокой производительности только при необходимости."),
                 ("USB selective suspend", "Позволяет Windows переводить неиспользуемые USB-устройства в энергосбережение.", "TEST", "Не отключать без причины: это обычно не повышает FPS и может увеличить энергопотребление."),
                 ("Mouse acceleration", "Меняет зависимость перемещения указателя от скорости движения мыши.", "SAFE", "Отключение может сделать управление более предсказуемым, но не повышает средний FPS."),
                 ("Keyboard / multimedia scheduler tweaks", "Изменяет параметры обработки ввода и мультимедийных задач.", "CAUTION", "Не применять неизвестные latency-твики без измерений.")
             ]),
            ("4. GAMING FEATURES", "Функции Windows, связанные с играми и захватом.",
             "Настройки игрового режима, записи клипов, полноэкранного режима и графического планирования.",
             "Возможное влияние на FPS: обычно небольшое; может уменьшить лишнюю фоновую запись.",
             [
                 ("Windows Game Mode", "Помогает Windows отдавать приоритет активной игре.", "SAFE", "Включено основным профилем программы."),
                 ("Game DVR / background capture", "Записывает игровой процесс в фоне.", "SAFE", "Отключено основным профилем, если запись в фоне не нужна."),
                 ("Fullscreen optimizations", "Обеспечивает совместимость полноэкранного режима и современных оконных функций.", "TEST", "Не отключать глобально: сравнивать отдельно для конкретной игры."),
                 ("HAGS", "Аппаратное планирование GPU.", "TEST", "Проверять включённое и выключенное состояние отдельно.")
             ]),
            ("5. PRIVACY & BACKGROUND ACTIVITY", "Телеметрия, рекламные предложения и фоновые рекомендации.",
             "Уменьшает часть фоновой активности и персонализированных предложений Windows.",
             "Возможное влияние на FPS: практически всегда косвенное и небольшое; это в первую очередь приватность.",
             [
                 ("Advertising ID и персонализация рекламы", "Ограничивает использование рекламного идентификатора.", "SAFE", "На FPS заметно не влияет."),
                 ("Диагностические данные и error reporting", "Управляет частью диагностической и отчётной активности.", "TEST", "Не отключать службы диагностики массово; некоторые параметры ограничены редакцией Windows."),
                 ("Location / suggestions / consumer content", "Управляет разрешениями местоположения и рекомендациями интерфейса.", "SAFE", "В основном влияет на приватность и удобство, не на игровой FPS."),
                 ("Windows Update / Defender / Firewall", "Обновления и базовая защита системы.", "KEEP ON", "Оставить включёнными. Не отключать ради FPS.")
             ]),
            ("6. STARTUP, TASKS & BLOATWARE", "Автозагрузка, запланированные задачи и предустановленные приложения.",
             "Помогает найти программы, которые запускаются сами и расходуют RAM, CPU, диск или сеть.",
             "Возможное влияние на FPS: косвенное; может помочь при ограниченных 16 ГБ RAM и HDD.",
             [
                 ("Startup Manager", "Показывает приложения автозагрузки.", "SAFE", "Отключать только узнаваемые необязательные приложения."),
                 ("Scheduled Tasks", "Показывает задачи, запускаемые по расписанию.", "CAUTION", "Не отключать неизвестные системные задачи."),
                 ("AppX / Bloatware", "Позволяет управлять предустановленными приложениями.", "CAUTION", "Удалять только явно ненужные пользовательские приложения; не удалять компоненты Windows.")
             ]),
            ("7. DISK & STORAGE", "Временные файлы, кэш и состояние накопителей.",
             "Освобождает место и уменьшает конкуренцию за HDD во время игры.",
             "Возможное влияние на FPS: обычно не повышает средний FPS, но может уменьшить задержки при нехватке места или активной работе диска.",
             [
                 ("Temporary files cleanup", "Удаляет выбранные временные файлы.", "SAFE", "Перед удалением показывать список и размер; не удалять Downloads автоматически."),
                 ("Windows Update leftovers / crash dumps", "Освобождает место за счёт старых файлов обновлений и отчётов сбоев.", "TEST", "Удаление может лишить возможности быстро откатить некоторые обновления."),
                 ("HDD optimization", "Штатная оптимизация HDD по расписанию.", "SAFE", "Не запускать во время игры; не использовать дефрагментацию для SSD.")
             ]),
            ("8. USER EXPERIENCE", "Анимации, прозрачность, меню и поведение рабочего стола.",
             "Делает интерфейс Windows визуально проще и отзывчивее.",
             "Возможное влияние на FPS в играх: почти нулевое; в основном влияет на отзывчивость рабочего стола.",
             [
                 ("Menu show delay / animations", "Меняет скорость появления меню и анимаций.", "SAFE", "Можно оставить стандартные значения, чтобы сохранить внешний вид Windows."),
                 ("Transparency / taskbar effects", "Управляет визуальными эффектами рабочего стола.", "SAFE", "В этом профиле не отключаются — сохраняем красивый интерфейс Windows."),
                 ("Dark mode / Explorer preferences", "Настройки внешнего вида и Проводника.", "SAFE", "На FPS игр практически не влияют.")
             ])
        ]

        risk_colors = {"SAFE": "#42c982", "TEST": "#e8bd57", "CAUTION": "#e8a45c", "KEEP ON": "#42c982"}
        for title, subtitle, purpose, impact, entries in groups:
            card = tk.Frame(content, bg="#1a2330", padx=12, pady=10)
            card.pack(fill="x", pady=6)
            tk.Label(card, text=title, bg="#1a2330", fg="#ffffff",
                     font=("Segoe UI Semibold", 11)).pack(anchor="w")
            tk.Label(card, text=subtitle, bg="#1a2330", fg="#91a8c2",
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 5))
            tk.Label(card, text=purpose, bg="#1a2330", fg="#d4deea",
                     justify="left", wraplength=660).pack(anchor="w")
            tk.Label(card, text=impact, bg="#1a2330", fg="#aab8ca",
                     justify="left", wraplength=660).pack(anchor="w", pady=(3, 7))
            for name, desc, risk, effect in entries:
                row = tk.Frame(card, bg="#202d3d", padx=8, pady=6)
                row.pack(fill="x", pady=3)
                head = tk.Frame(row, bg="#202d3d")
                head.pack(fill="x")
                tk.Label(head, text=name, bg="#202d3d", fg="#ffffff",
                         font=("Segoe UI Semibold", 9)).pack(side="left", anchor="w")
                tk.Label(head, text=risk, bg="#202d3d", fg=risk_colors[risk],
                         font=("Segoe UI", 8, "bold")).pack(side="right")
                tk.Label(row, text=desc + "\n" + effect, bg="#202d3d", fg="#bdcadd",
                         justify="left", wraplength=640, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        tk.Label(content,
                 text="Важно: это каталог функций и объяснений, а не кнопка массового применения. В текущей версии автоматически применяются только безопасные Game Mode и отключение фоновой записи. Остальные пункты требуют отдельной реализации, проверки и резервного отката.",
                 bg="#10151e", fg="#e8bd57", justify="left", wraplength=680).pack(fill="x", pady=12)
        ttk.Button(outer, text="ЗАКРЫТЬ", command=win.destroy).pack(anchor="e", pady=(8, 0))


if __name__ == "__main__":
    if os.name != "nt":
        print("This application is intended for Windows 11.")
        sys.exit(1)
    App().mainloop()