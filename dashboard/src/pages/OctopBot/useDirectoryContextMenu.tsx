import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";
import { Dropdown, type MenuProps } from "antd";
import styles from "./sections.module.less";

type ContextEvent = MouseEvent<HTMLElement> | KeyboardEvent<HTMLElement>;
type OpenMenu = {
  menu: MenuProps;
  x: number;
  y: number;
  returnTo: HTMLElement;
  id: number;
};
const isBackground = (target: EventTarget | null) =>
  target instanceof Element &&
  !target.closest(
    "button, a, input, textarea, select, [role=menu], [data-directory-item], [data-section-header]",
  );

export function useDirectoryContextMenu(
  revision: number | undefined,
  path: string,
  drawerOpen: boolean,
) {
  const [open, setOpen] = useState<OpenMenu | null>(null);
  const [overflow, setOverflow] = useState<string | null>(null);
  const serial = useRef(0);
  const hold = useRef<ReturnType<typeof setTimeout>>();
  const touchStart = useRef({ x: 0, y: 0 });
  const cancelHold = useCallback(() => clearTimeout(hold.current), []);
  useEffect(() => {
    setOpen(null);
    setOverflow(null);
    return cancelHold;
  }, [revision, path, drawerOpen, cancelHold]);

  // Stable handlers let memoized directory rows skip unrelated renders.
  const events = useCallback(
    (menu: MenuProps, background = false) => {
      const show = (event: ContextEvent) => {
        if (
          !(event.target instanceof Element) ||
          !event.currentTarget.contains(event.target)
        )
          return;
        if (
          background &&
          event.target !== event.currentTarget &&
          !isBackground(event.target)
        )
          return;
        const keyboard = "key" in event;
        if (
          keyboard &&
          event.key !== "ContextMenu" &&
          !(event.key === "F10" && event.shiftKey)
        )
          return;
        event.preventDefault();
        event.stopPropagation();
        cancelHold();
        const returnTo =
          event.target.closest<HTMLElement>("button,[tabindex]") ||
          event.currentTarget;
        const bounds = returnTo.getBoundingClientRect();
        setOverflow(null);
        setOpen({
          menu,
          x: keyboard ? bounds.left + 8 : event.clientX,
          y: keyboard
            ? bounds.top + Math.min(28, bounds.height)
            : event.clientY,
          returnTo,
          id: ++serial.current,
        });
      };
      return { onContextMenu: show, onKeyDown: show };
    },
    [cancelHold],
  );
  // On touch-only systems the first workspace may have only Chief and no row menu.
  const touchBackground = useCallback(
    (menu: MenuProps) => ({
      onPointerDown: (e: PointerEvent<HTMLElement>) => {
        cancelHold();
        if (
          e.pointerType !== "touch" ||
          !e.currentTarget.contains(e.target as Node) ||
          !isBackground(e.target)
        )
          return;
        const { clientX: x, clientY: y, currentTarget: returnTo } = e;
        touchStart.current = { x, y };
        hold.current = setTimeout(() => {
          setOverflow(null);
          setOpen({ menu, x, y, returnTo, id: ++serial.current });
        }, 550);
      },
      onPointerUp: cancelHold,
      onPointerMove: (e: PointerEvent<HTMLElement>) => {
        if (
          Math.hypot(
            e.clientX - touchStart.current.x,
            e.clientY - touchStart.current.y,
          ) > 8
        )
          cancelHold();
      },
      onPointerCancel: cancelHold,
      onScroll: cancelHold,
    }),
    [cancelHold],
  );
  const popup = open && (
    <Dropdown
      key={open.id}
      open
      autoFocus
      trigger={["click"]}
      onOpenChange={(visible) => {
        if (!visible) setOpen(null);
      }}
      placement="bottomLeft"
      menu={{
        ...open.menu,
        onKeyDown: (e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            setOpen(null);
            open.returnTo.focus({ preventScroll: true });
          }
        },
      }}
    >
      <span
        className={styles.menuAnchor}
        aria-hidden
        style={{ left: open.x, top: open.y }}
      />
    </Dropdown>
  );
  const overflowProps = useCallback(
    (id: string) => ({
      open: overflow === id,
      onOpenChange: (visible: boolean) => {
        if (visible) setOpen(null);
        setOverflow((previous) =>
          visible ? id : previous === id ? null : previous,
        );
      },
    }),
    [overflow],
  );
  return { events, touchBackground, overflowProps, popup };
}
export type DirectoryMenuEvents = ReturnType<
  typeof useDirectoryContextMenu
>["events"];
