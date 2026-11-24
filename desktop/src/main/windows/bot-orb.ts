import {
  BrowserWindow,
  Menu,
  app,
  ipcMain,
  screen,
  type Point,
  type Rectangle,
} from "electron";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { IPC_CHANNELS, type BotShortcut } from "../../shared/ipc-contract";
import { desktopLog } from "../log/desktop-log";
import { uiLocale } from "../ui-locale";

const size = 64;
type OrbAction = BotShortcut | "resume" | "settings";

function within(point: Point, area: Rectangle): Point {
  return {
    x: Math.round(
      Math.max(area.x, Math.min(point.x, area.x + area.width - size)),
    ),
    y: Math.round(
      Math.max(area.y, Math.min(point.y, area.y + area.height - size)),
    ),
  };
}

export class BotOrb {
  window: BrowserWindow | null = null;
  private position?: Point;
  private dragStart?: Point;
  private hidden = false;
  private readonly file = join(app.getPath("userData"), "bot-orb.json");

  constructor(private readonly run: (action: OrbAction) => void) {
    if (existsSync(this.file)) {
      try {
        const saved = JSON.parse(readFileSync(this.file, "utf8"));
        this.hidden = saved.hidden === true;
        if (Number.isFinite(saved.x) && Number.isFinite(saved.y))
          this.position = { x: saved.x, y: saved.y };
      } catch (err) {
        desktopLog().warn(
          "Could not read floating button settings: " + String(err),
        );
      }
    }
    ipcMain.on(
      IPC_CHANNELS.orbPointer,
      (event, action: unknown, dx: number, dy: number) => {
        const win = this.window;
        if (!win || event.sender !== win.webContents) return;
        if (action === "start") {
          this.dragStart = win.getBounds();
        } else if (
          action === "move" &&
          this.dragStart &&
          Number.isFinite(dx) &&
          Number.isFinite(dy)
        ) {
          const pt = within(
            { x: this.dragStart.x + dx, y: this.dragStart.y + dy },
            screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
              .workArea,
          );
          win.setPosition(pt.x, pt.y);
        } else if (action === "end" && this.dragStart) {
          const { x, y } = win.getBounds();
          if (x !== this.dragStart.x || y !== this.dragStart.y) {
            this.position = { x, y };
            this.save();
          }
          this.dragStart = undefined;
        } else if (action === "menu") {
          this.menu(win);
        }
      },
    );
    const reposition = () => {
      if (!this.window || this.dragStart) return;
      const { x, y } = this.bounds();
      this.window.setPosition(x, y);
    };
    screen.on("display-removed", reposition);
    screen.on("display-metrics-changed", reposition);
  }

  private save(): void {
    try {
      writeFileSync(
        this.file + ".tmp",
        JSON.stringify({ ...this.position, hidden: this.hidden }),
      );
      renameSync(this.file + ".tmp", this.file);
    } catch (err) {
      desktopLog().warn(
        "Could not save floating button settings: " + String(err),
      );
    }
  }

  private bounds(): Point {
    const area = (
      this.position
        ? screen.getDisplayNearestPoint(this.position)
        : screen.getPrimaryDisplay()
    ).workArea;
    return within(
      this.position ?? {
        x: area.x + area.width - size - 16,
        y: area.y + area.height * 0.65,
      },
      area,
    );
  }

  show(restore = false): void {
    if (this.hidden && !restore) return;
    if (this.hidden) {
      this.hidden = false;
      this.save();
    }
    if (this.window) {
      this.window.showInactive();
      return;
    }
    const win = new BrowserWindow({
      ...this.bounds(),
      width: size,
      height: size,
      title:
        "Octop Bot · " +
        (uiLocale().startsWith("zh") ? "悬浮球" : "Floating button"),
      show: false,
      frame: false,
      transparent: true,
      backgroundColor: "#00000000",
      resizable: false,
      maximizable: false,
      minimizable: false,
      fullscreenable: false,
      skipTaskbar: true,
      alwaysOnTop: true,
      hasShadow: false,
      autoHideMenuBar: true,
      webPreferences: {
        preload: join(__dirname, "../preload/orb.js"),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
      },
    });
    this.window = win;
    win.webContents.on("page-title-updated", (event) => event.preventDefault());
    win.webContents.on("will-navigate", (event) => event.preventDefault());
    win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    win.once("closed", () => {
      this.window = null;
      this.dragStart = undefined;
    });
    win.once("ready-to-show", () => {
      if (!win.isDestroyed() && !this.hidden) win.showInactive();
    });
    void win.loadFile(join(__dirname, "../renderer/orb.html")).catch((err) => {
      if (!win.isDestroyed()) {
        desktopLog().warn("Floating button load failed: " + String(err));
        win.destroy();
      }
    });
  }

  private menu(win: BrowserWindow): void {
    const zh = uiLocale().toLowerCase().startsWith("zh");
    const item = (label: string, action: OrbAction) => ({
      label,
      click: () => this.run(action),
    });
    Menu.buildFromTemplate([
      item(zh ? "打开 Bot 主窗口" : "Open Bot window", "resume"),
      item(zh ? "新建对话" : "New chat", "newChat"),
      item(zh ? "搜索团队和会话" : "Search team and chats", "search"),
      { type: "separator" },
      item(zh ? "云端工作区" : "Cloud workspace", "cloud"),
      item(zh ? "账号与模型" : "Account and models", "settings"),
      { type: "separator" },
      {
        label: zh ? "隐藏悬浮球" : "Hide floating button",
        click: () => {
          this.hidden = true;
          this.save();
          win.hide();
        },
      },
    ]).popup({ window: win });
  }
}
