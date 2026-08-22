#[cfg(windows)]
pub mod windows {
    use std::mem::size_of;
    use std::sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    };
    use std::thread::{self, JoinHandle};
    use std::time::Duration;

    use crossbeam_channel::{Receiver, bounded};
    use windows::Win32::Foundation::{LPARAM, RECT};
    use windows::Win32::Graphics::Gdi::{
        EnumDisplayMonitors, GetMonitorInfoW, HDC, HMONITOR, MONITOR_DEFAULTTONEAREST, MONITORINFO,
        MONITORINFOEXW, MonitorFromWindow,
    };
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        MOD_CONTROL, MOD_SHIFT, RegisterHotKey, UnregisterHotKey,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        GetForegroundWindow, MONITORINFOF_PRIMARY, MSG, PM_REMOVE, PeekMessageW, WM_HOTKEY,
    };
    use windows::core::BOOL;

    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Monitor {
        pub handle: isize,
        pub name: String,
        pub x: i32,
        pub y: i32,
        pub width: i32,
        pub height: i32,
        pub is_primary: bool,
    }

    unsafe extern "system" fn collect_monitor(
        handle: HMONITOR,
        _device_context: HDC,
        _rect: *mut RECT,
        state: LPARAM,
    ) -> BOOL {
        let monitors = unsafe { &mut *(state.0 as *mut Vec<Monitor>) };
        let mut info = MONITORINFOEXW::default();
        info.monitorInfo.cbSize = size_of::<MONITORINFOEXW>() as u32;
        if unsafe {
            GetMonitorInfoW(
                handle,
                (&mut info as *mut MONITORINFOEXW).cast::<MONITORINFO>(),
            )
        }
        .as_bool()
        {
            let end = info
                .szDevice
                .iter()
                .position(|character| *character == 0)
                .unwrap_or(info.szDevice.len());
            let name = String::from_utf16_lossy(&info.szDevice[..end]);
            let rect = info.monitorInfo.rcMonitor;
            monitors.push(Monitor {
                handle: handle.0 as isize,
                name,
                x: rect.left,
                y: rect.top,
                width: rect.right - rect.left,
                height: rect.bottom - rect.top,
                is_primary: info.monitorInfo.dwFlags & MONITORINFOF_PRIMARY != 0,
            });
        }
        BOOL(1)
    }

    pub fn enumerate_monitors() -> Vec<Monitor> {
        let mut monitors = Vec::new();
        unsafe {
            let _ = EnumDisplayMonitors(
                None,
                None,
                Some(collect_monitor),
                LPARAM((&mut monitors as *mut Vec<Monitor>) as isize),
            );
        }
        monitors
    }

    pub fn active_monitor() -> Option<Monitor> {
        let foreground = unsafe { GetForegroundWindow() };
        if foreground.0.is_null() {
            return enumerate_monitors()
                .into_iter()
                .find(|monitor| monitor.is_primary);
        }
        let active = unsafe { MonitorFromWindow(foreground, MONITOR_DEFAULTTONEAREST) };
        enumerate_monitors()
            .into_iter()
            .find(|monitor| monitor.handle == active.0 as isize)
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub enum HotkeyEvent {
        ToggleSubtitles,
        ToggleOverlay,
        IncreaseText,
        DecreaseText,
        ToggleLock,
    }

    pub struct GlobalHotkeys {
        events: Receiver<HotkeyEvent>,
        stop: Arc<AtomicBool>,
        thread: Option<JoinHandle<()>>,
    }

    impl GlobalHotkeys {
        pub fn register() -> Self {
            const HOTKEYS: [(i32, u32, HotkeyEvent); 5] = [
                (1, b'S' as u32, HotkeyEvent::ToggleSubtitles),
                (2, b'H' as u32, HotkeyEvent::ToggleOverlay),
                (3, 0x26, HotkeyEvent::IncreaseText),
                (4, 0x28, HotkeyEvent::DecreaseText),
                (5, b'L' as u32, HotkeyEvent::ToggleLock),
            ];
            let (sender, receiver) = bounded(16);
            let stop = Arc::new(AtomicBool::new(false));
            let thread_stop = Arc::clone(&stop);
            let thread = thread::Builder::new()
                .name("livesub-hotkeys".into())
                .spawn(move || unsafe {
                    for (id, key, _) in HOTKEYS {
                        if let Err(error) = RegisterHotKey(None, id, MOD_CONTROL | MOD_SHIFT, key) {
                            tracing::warn!(%error, id, key, "could not register global hotkey");
                        }
                    }
                    let mut message = MSG::default();
                    while !thread_stop.load(Ordering::Acquire) {
                        while PeekMessageW(&mut message, None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE)
                            .as_bool()
                        {
                            if let Some((_, _, event)) = HOTKEYS
                                .iter()
                                .find(|(id, _, _)| *id == message.wParam.0 as i32)
                            {
                                let _ = sender.try_send(*event);
                            }
                        }
                        thread::sleep(Duration::from_millis(20));
                    }
                    for (id, _, _) in HOTKEYS {
                        let _ = UnregisterHotKey(None, id);
                    }
                })
                .ok();
            Self {
                events: receiver,
                stop,
                thread,
            }
        }

        pub fn events(&self) -> &Receiver<HotkeyEvent> {
            &self.events
        }
    }

    impl Drop for GlobalHotkeys {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::Release);
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
        }
    }
}
