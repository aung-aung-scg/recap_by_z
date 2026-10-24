from __future__ import annotations

import tkinter as tk


def _colorref(color: str) -> int:
    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return r | (g << 8) | (b << 16)


class NativeTextBox:
    """Windows RichEdit control for correctly shaped Myanmar text."""

    WS_CHILD, WS_VISIBLE, WS_VSCROLL, WS_CLIPCHILDREN = 0x40000000, 0x10000000, 0x00200000, 0x02000000
    ES_MULTILINE, ES_AUTOVSCROLL, ES_NOHIDESEL, ES_WANTRETURN = 0x0004, 0x0040, 0x0100, 0x1000
    EM_SETBKGNDCOLOR, EM_SETCHARFORMAT, EM_SETTEXTMODE = 0x0443, 0x0444, 0x0459
    EM_EMPTYUNDOBUFFER, EM_SETMARGINS = 0x00CD, 0x00D3
    GWL_STYLE = -16

    def __init__(self, frame: tk.Frame, *, font: str, size_pt: int, bg: str, fg: str) -> None:
        import ctypes
        from ctypes import wintypes

        class CHARFORMAT2W(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT), ("dwMask", wintypes.DWORD), ("dwEffects", wintypes.DWORD),
                ("yHeight", wintypes.LONG), ("yOffset", wintypes.LONG), ("crTextColor", wintypes.DWORD),
                ("bCharSet", wintypes.BYTE), ("bPitchAndFamily", wintypes.BYTE),
                ("szFaceName", wintypes.WCHAR * 32), ("wWeight", wintypes.WORD), ("sSpacing", ctypes.c_short),
                ("crBackColor", wintypes.DWORD), ("lcid", wintypes.DWORD), ("dwReserved", wintypes.DWORD),
                ("sStyle", ctypes.c_short), ("wKerning", wintypes.WORD), ("bUnderlineType", wintypes.BYTE),
                ("bAnimation", wintypes.BYTE), ("bRevAuthor", wintypes.BYTE), ("bUnderlineColor", wintypes.BYTE),
            ]

        self.frame = frame
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        ctypes.WinDLL("Msftedit.dll")
        user32 = self.user32
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]

        frame.update_idletasks()
        parent = wintypes.HWND(frame.winfo_id())
        user32.SetWindowLongW(parent, self.GWL_STYLE, user32.GetWindowLongW(parent, self.GWL_STYLE) | self.WS_CLIPCHILDREN)
        style = (
            self.WS_CHILD | self.WS_VISIBLE | self.WS_VSCROLL | self.ES_MULTILINE
            | self.ES_AUTOVSCROLL | self.ES_NOHIDESEL | self.ES_WANTRETURN
        )
        self.hwnd = user32.CreateWindowExW(
            0, "RICHEDIT50W", "", style, 0, 0, max(50, frame.winfo_width()),
            max(50, frame.winfo_height()), parent, None, None, None,
        )
        if not self.hwnd:
            raise OSError(f"RichEdit could not be created (error {ctypes.get_last_error()})")
        user32.SendMessageW(self.hwnd, self.EM_SETTEXTMODE, 1, 0)
        user32.SendMessageW(self.hwnd, self.EM_SETBKGNDCOLOR, 0, _colorref(bg))
        char_format = CHARFORMAT2W()
        char_format.cbSize = ctypes.sizeof(CHARFORMAT2W)
        char_format.dwMask = 0x40000000 | 0x20000000 | 0x80000000
        char_format.crTextColor = _colorref(fg)
        char_format.yHeight = int(size_pt) * 20
        char_format.szFaceName = font
        for scope in (0, 4):
            user32.SendMessageW(self.hwnd, self.EM_SETCHARFORMAT, scope, ctypes.addressof(char_format))
        user32.SendMessageW(self.hwnd, self.EM_SETMARGINS, 0x1 | 0x2, (10 << 16) | 10)
        self._fmt = char_format
        frame.bind("<Configure>", self._resize, add="+")

    def _resize(self, event) -> None:
        self.user32.MoveWindow(self.hwnd, 0, 0, int(event.width), int(event.height), True)

    def get(self) -> str:
        import ctypes
        length = self.user32.GetWindowTextLengthW(self.hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(self.hwnd, buffer, length + 1)
        return buffer.value

    def set(self, text: str) -> None:
        import ctypes
        self.user32.SetWindowTextW(self.hwnd, str(text))
        self.user32.SendMessageW(self.hwnd, self.EM_SETCHARFORMAT, 4, ctypes.addressof(self._fmt))
        self.user32.SendMessageW(self.hwnd, self.EM_EMPTYUNDOBUFFER, 0, 0)

    def focus(self) -> None:
        self.user32.SetFocus(self.hwnd)
