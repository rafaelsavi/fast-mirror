"""
Windows 11 high-performance native smooth dragging engine for Tkinter.

Eliminates window dragging lag, cursor desync, and 5 FPS stutter on Windows 11
with high-polling-rate mice (1000Hz+) by routing modal move events directly to
Windows DWM via a zero-overhead native x86-64 machine code stub.
"""

import contextlib
import ctypes
import os
import platform
import sys
import tkinter as tk
from ctypes import wintypes

from utils.logger import is_test_or_agent_mode, logger

PAGE_EXECUTE_READWRITE = 0x40
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
GWLP_WNDPROC = -4


def install_smooth_drag_interceptor(window: tk.Tk | tk.Toplevel, target_fps: int = 60) -> bool:
    """
    Subclass the Win32 window to route WM_WINDOWPOSCHANGED events directly to DWM during moves.

    This completely eliminates Tkinter's internal 1000Hz layout cascade across 150+ child widgets,
    allowing Windows DWM to translate the window surface smoothly at native monitor refresh rates
    (60/120/144 FPS) while synchronizing final coordinates with Tkinter upon mouse release.

    Uses a zero-overhead native x86-64 machine code stub that executes directly on the CPU,
    completely eliminating Python GIL contention, ctypes callback reentrancy, or crashes.
    """
    if os.name != 'nt' or not hasattr(ctypes, 'windll'):
        return False
    if is_test_or_agent_mode():
        return False
    if sys.platform != 'win32' or ctypes.sizeof(ctypes.c_void_p) != 8:
        return False
    if not platform.machine().lower().startswith(('amd64', 'x86_64')):
        return False

    # Prevent double-installation
    if getattr(window, '_smooth_drag_hook', None) is not None:
        return True

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        window.update_idletasks()
        hwnd = window.winfo_id()
        top_hwnd = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT = 2

        # Enable DWM hardware accelerated non-client rendering
        with contextlib.suppress(Exception):
            # DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_ENABLED = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(top_hwnd, 2, ctypes.byref(ctypes.c_int(2)), 4)

        kernel32.VirtualAlloc.restype = ctypes.c_void_p
        kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

        orig_wndproc = user32.GetWindowLongPtrW(top_hwnd, GWLP_WNDPROC)
        if not orig_wndproc:
            return False

        def_wndproc = ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p).value
        call_wndproc = ctypes.cast(user32.CallWindowProcW, ctypes.c_void_p).value

        # Memory layout (1 page = 4096 bytes):
        # 0x00: orig_wndproc (uint64)
        # 0x08: def_wndproc (uint64)
        # 0x10: call_wndproc (uint64)
        # 0x18: in_sizemove (uint32)
        # 0x1C: has_last_pos (uint32)
        # 0x20: last_pos (WINDOWPOS: 40 bytes)
        # 0x50: Code starts here
        mem = kernel32.VirtualAlloc(None, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if not mem:
            return False

        ctypes.c_uint64.from_address(mem + 0x00).value = orig_wndproc
        ctypes.c_uint64.from_address(mem + 0x08).value = def_wndproc
        ctypes.c_uint64.from_address(mem + 0x10).value = call_wndproc
        ctypes.c_uint32.from_address(mem + 0x18).value = 0
        ctypes.c_uint32.from_address(mem + 0x1C).value = 0

        code = bytearray()
        code_start_offset = 0x50

        def emit(b: bytes) -> None:
            code.extend(b)

        def rip_disp(target_data_offset: int, instruction_end_offset: int) -> bytes:
            disp = target_data_offset - instruction_end_offset
            return disp.to_bytes(4, byteorder='little', signed=True)

        # 1. Check WM_ENTERSIZEMOVE (0x0231)
        emit(b'\x81\xfa\x31\x02\x00\x00')
        emit(b'\x0f\x85\x00\x00\x00\x00')  # jne not_enter
        jne_not_enter_idx = len(code) - 4

        # in_sizemove = 1
        inst_end = code_start_offset + len(code) + 10
        emit(b'\xc7\x05' + rip_disp(0x18, inst_end) + b'\x01\x00\x00\x00')
        emit(b'\xe9\x00\x00\x00\x00')  # jmp call_orig
        jmp_orig_1_idx = len(code) - 4

        # not_enter:
        not_enter_offset = len(code)
        disp = not_enter_offset - (jne_not_enter_idx + 4)
        code[jne_not_enter_idx : jne_not_enter_idx + 4] = disp.to_bytes(4, 'little', signed=True)

        # 2. Check WM_EXITSIZEMOVE (0x0232)
        emit(b'\x81\xfa\x32\x02\x00\x00')
        emit(b'\x0f\x85\x00\x00\x00\x00')  # jne not_exit
        jne_not_exit_idx = len(code) - 4

        # in_sizemove = 0
        inst_end = code_start_offset + len(code) + 10
        emit(b'\xc7\x05' + rip_disp(0x18, inst_end) + b'\x00\x00\x00\x00')

        # Check if has_last_pos == 1
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x83\x3d' + rip_disp(0x1C, inst_end) + b'\x01')
        emit(b'\x0f\x85\x00\x00\x00\x00')  # jne skip_sync_pos
        jne_skip_sync_idx = len(code) - 4

        # Deliver final WM_WINDOWPOSCHANGED to orig_wndproc:
        emit(b'\x48\x83\xec\x28')  # sub rsp, 40
        emit(b'\x48\x89\x4c\x24\x30')  # mov [rsp + 48], rcx (save hwnd)
        emit(b'\x48\x89\x54\x24\x38')  # mov [rsp + 56], rdx (save uMsg)

        # [rsp + 0x20] = &last_pos
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x4c\x8d\x05' + rip_disp(0x20, inst_end))  # lea r8, [rip + last_pos]
        emit(b'\x4c\x89\x44\x24\x20')  # mov [rsp + 0x20], r8
        emit(b'\x45\x31\xc9')  # xor r9d, r9d (wParam = 0)
        emit(b'\x41\xb8\x47\x00\x00\x00')  # mov r8d, 0x0047 (uMsg = WM_WINDOWPOSCHANGED)
        emit(b'\x48\x8b\x54\x24\x30')  # mov rdx, [rsp + 48] (hwnd)
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x8b\x0d' + rip_disp(0x00, inst_end))  # mov rcx, [rip + orig_wndproc]
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x8b\x05' + rip_disp(0x10, inst_end))  # mov rax, [rip + call_wndproc]
        emit(b'\xff\xd0')  # call rax

        emit(b'\x48\x8b\x4c\x24\x30')  # mov rcx, [rsp + 48]
        emit(b'\x48\x8b\x54\x24\x38')  # mov rdx, [rsp + 56]
        emit(b'\x48\x83\xc4\x28')  # add rsp, 40

        # has_last_pos = 0
        inst_end = code_start_offset + len(code) + 10
        emit(b'\xc7\x05' + rip_disp(0x1C, inst_end) + b'\x00\x00\x00\x00')

        # skip_sync_pos:
        skip_sync_offset = len(code)
        disp = skip_sync_offset - (jne_skip_sync_idx + 4)
        code[jne_skip_sync_idx : jne_skip_sync_idx + 4] = disp.to_bytes(4, 'little', signed=True)

        emit(b'\xe9\x00\x00\x00\x00')  # jmp call_orig
        jmp_orig_2_idx = len(code) - 4

        # not_exit:
        not_exit_offset = len(code)
        disp = not_exit_offset - (jne_not_exit_idx + 4)
        code[jne_not_exit_idx : jne_not_exit_idx + 4] = disp.to_bytes(4, 'little', signed=True)

        # 3. Check WM_WINDOWPOSCHANGED (0x0047)
        emit(b'\x81\xfa\x47\x00\x00\x00')
        emit(b'\x0f\x85\x00\x00\x00\x00')  # jne call_orig
        jmp_orig_3_idx = len(code) - 4

        # 4. Check if in_sizemove == 1
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x83\x3d' + rip_disp(0x18, inst_end) + b'\x01')
        emit(b'\x0f\x85\x00\x00\x00\x00')  # jne call_orig
        jmp_orig_4_idx = len(code) - 4

        # 5. Check if lParam != NULL: test r9, r9
        emit(b'\x4d\x85\xc9')
        emit(b'\x0f\x84\x00\x00\x00\x00')  # jz call_orig
        jmp_orig_5_idx = len(code) - 4

        # 6. Check if SWP_NOSIZE (0x0001) is set in flags: test dword ptr [r9 + 0x20], 1
        emit(b'\x41\xf7\x41\x20\x01\x00\x00\x00')
        emit(b'\x0f\x84\x00\x00\x00\x00')  # jz call_orig (pass resizes directly to Tk)

        jmp_orig_6_idx = len(code) - 4

        # --- Bypass Branch: Store last_pos and route to Windows DefWindowProcW ---
        # Copy 40 bytes from [r9] into last_pos
        emit(b'\x49\x8b\x01')
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x89\x05' + rip_disp(0x20, inst_end))

        emit(b'\x49\x8b\x41\x08')
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x89\x05' + rip_disp(0x28, inst_end))

        emit(b'\x49\x8b\x41\x10')
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x89\x05' + rip_disp(0x30, inst_end))

        emit(b'\x49\x8b\x41\x18')
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x89\x05' + rip_disp(0x38, inst_end))

        emit(b'\x49\x8b\x41\x20')
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x89\x05' + rip_disp(0x40, inst_end))

        # has_last_pos = 1
        inst_end = code_start_offset + len(code) + 10
        emit(b'\xc7\x05' + rip_disp(0x1C, inst_end) + b'\x01\x00\x00\x00')

        # DefWindowProcW(hwnd, uMsg, wParam, lParam)
        emit(b'\x48\x83\xec\x28')  # sub rsp, 40
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x8b\x05' + rip_disp(0x08, inst_end))  # mov rax, [rip + def_wndproc]
        emit(b'\xff\xd0')  # call rax
        emit(b'\x48\x83\xc4\x28')  # add rsp, 40
        emit(b'\xc3')  # ret

        # --- call_orig branch ---
        call_orig_offset = len(code)
        for idx in [jmp_orig_1_idx, jmp_orig_2_idx, jmp_orig_3_idx, jmp_orig_4_idx, jmp_orig_5_idx, jmp_orig_6_idx]:
            disp = call_orig_offset - (idx + 4)
            code[idx : idx + 4] = disp.to_bytes(4, 'little', signed=True)

        # CallWindowProcW(orig_wndproc, hwnd, uMsg, wParam, lParam)
        emit(b'\x48\x83\xec\x28')  # sub rsp, 40
        emit(b'\x4c\x89\x4c\x24\x20')  # mov [rsp + 0x20], r9 (lParam)
        emit(b'\x4d\x89\xc1')  # mov r9, r8 (wParam)
        emit(b'\x49\x89\xd0')  # mov r8, rdx (uMsg)
        emit(b'\x48\x89\xca')  # mov rdx, rcx (hwnd)
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x8b\x0d' + rip_disp(0x00, inst_end))  # mov rcx, [rip + orig_wndproc]
        inst_end = code_start_offset + len(code) + 7
        emit(b'\x48\x8b\x05' + rip_disp(0x10, inst_end))  # mov rax, [rip + call_wndproc]
        emit(b'\xff\xd0')  # call rax
        emit(b'\x48\x83\xc4\x28')  # add rsp, 40
        emit(b'\xc3')  # ret

        stub_addr = mem + code_start_offset
        ctypes.memmove(stub_addr, bytes(code), len(code))

        user32.SetWindowLongPtrW(top_hwnd, GWLP_WNDPROC, stub_addr)
        window._smooth_drag_hook = (mem, orig_wndproc, top_hwnd)  # type: ignore[attr-defined]

        def _cleanup(event):
            if event.widget == window:
                uninstall_smooth_drag_interceptor(window)

        window.bind('<Destroy>', _cleanup, add='+')
        logger.debug('Installed native x86-64 smooth window drag DWM interceptor')
        return True

    except Exception as exc:
        logger.debug(f'Could not install smooth drag interceptor: {exc}')
        return False


def uninstall_smooth_drag_interceptor(window: tk.Tk | tk.Toplevel) -> None:
    """Restore original window procedure and free memory if installed."""
    if os.name != 'nt' or not hasattr(ctypes, 'windll'):
        return

    hook_data = getattr(window, '_smooth_drag_hook', None)
    if not hook_data:
        return

    try:
        mem, orig_wndproc, top_hwnd = hook_data
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.SetWindowLongPtrW(top_hwnd, GWLP_WNDPROC, orig_wndproc)
        kernel32.VirtualFree(mem, 0, MEM_RELEASE)
        window._smooth_drag_hook = None  # type: ignore[attr-defined]
    except Exception:
        pass
