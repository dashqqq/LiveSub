#[cfg(windows)]
pub mod windows {
    use std::ffi::c_void;
    use std::mem::size_of;
    use std::ptr;
    use std::sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    };
    use std::thread::{self, JoinHandle};
    use std::time::Duration;

    use anyhow::{Context, anyhow};
    use crossbeam_channel::{Sender, bounded};
    use windows::Win32::Foundation::{
        COLORREF, HINSTANCE, LPARAM, LRESULT, POINT, RECT, SIZE, WPARAM,
    };
    use windows::Win32::Graphics::Gdi::{
        AC_SRC_ALPHA, AC_SRC_OVER, BI_RGB, BITMAPINFO, BLENDFUNCTION, CLEARTYPE_QUALITY,
        CLIP_DEFAULT_PRECIS, CreateCompatibleDC, CreateDIBSection, CreateFontW, CreateRoundRectRgn,
        CreateSolidBrush, DEFAULT_CHARSET, DEFAULT_PITCH, DIB_RGB_COLORS, DT_CENTER, DT_NOPREFIX,
        DT_VCENTER, DT_WORDBREAK, DeleteDC, DeleteObject, DrawTextW, FF_SWISS, FW_SEMIBOLD,
        FillRgn, GetDC, HGDIOBJ, OUT_DEFAULT_PRECIS, ReleaseDC, SelectObject, SetBkMode,
        SetTextColor, TRANSPARENT,
    };
    use windows::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GWL_EXSTYLE,
        GetWindowLongPtrW, HTCAPTION, HWND_TOPMOST, IDC_ARROW, LoadCursorW, MSG, PM_REMOVE,
        PeekMessageW, RegisterClassW, SW_HIDE, SW_SHOWNOACTIVATE, SWP_NOACTIVATE, SWP_SHOWWINDOW,
        SetWindowLongPtrW, SetWindowPos, ShowWindow, TranslateMessage, ULW_ALPHA,
        UpdateLayeredWindow, WM_NCHITTEST, WM_QUIT, WNDCLASSW, WS_EX_LAYERED, WS_EX_NOACTIVATE,
        WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
    };
    use windows::core::PCWSTR;

    const CLASS_NAME: &str = "LiveSubNativeOverlay_0_1";
    const WINDOW_TITLE: &str = "LiveSub Overlay";

    #[derive(Clone, Debug, PartialEq)]
    pub struct OverlayFrame {
        pub text: String,
        pub visible: bool,
        pub locked: bool,
        pub x: i32,
        pub y: i32,
        pub width: i32,
        pub height: i32,
        pub font_size: f32,
        pub background_alpha: u8,
        pub corner_radius: u8,
        pub tentative: bool,
    }

    impl Default for OverlayFrame {
        fn default() -> Self {
            Self {
                text: String::new(),
                visible: false,
                locked: true,
                x: 0,
                y: 0,
                width: 900,
                height: 190,
                font_size: 34.0,
                background_alpha: 190,
                corner_radius: 10,
                tentative: false,
            }
        }
    }

    pub struct NativeOverlay {
        frames: Sender<OverlayFrame>,
        stop: Arc<AtomicBool>,
        thread: Option<JoinHandle<()>>,
    }

    impl NativeOverlay {
        pub fn start() -> anyhow::Result<Self> {
            let (sender, receiver) = bounded::<OverlayFrame>(1);
            let stop = Arc::new(AtomicBool::new(false));
            let thread_stop = Arc::clone(&stop);
            let (ready_sender, ready_receiver) = bounded(1);
            let thread_ready = ready_sender.clone();
            let thread = thread::Builder::new()
                .name("livesub-overlay".into())
                .spawn(move || {
                    let result = unsafe { run_overlay(receiver, thread_stop, thread_ready) };
                    if let Err(error) = &result {
                        tracing::error!(%error, "native overlay stopped");
                        let _ = ready_sender.try_send(Err(anyhow!("{error:#}")));
                    }
                })
                .context("spawn native overlay thread")?;

            let readiness = ready_receiver
                .recv_timeout(Duration::from_secs(2))
                .context("native overlay did not initialize within two seconds");
            match readiness {
                Ok(Ok(())) => {}
                Ok(Err(error)) => {
                    stop.store(true, Ordering::Release);
                    let _ = thread.join();
                    return Err(error);
                }
                Err(error) => {
                    stop.store(true, Ordering::Release);
                    let _ = thread.join();
                    return Err(error);
                }
            }
            Ok(Self {
                frames: sender,
                stop,
                thread: Some(thread),
            })
        }

        pub fn update(&self, frame: OverlayFrame) {
            // A full channel contains a newer-enough visual state; dropping a
            // stale repaint is preferable to building an unbounded UI queue.
            let _ = self.frames.try_send(frame);
        }
    }

    impl Drop for NativeOverlay {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::Release);
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
        }
    }

    unsafe extern "system" fn overlay_window_proc(
        window: windows::Win32::Foundation::HWND,
        message: u32,
        wparam: WPARAM,
        lparam: LPARAM,
    ) -> LRESULT {
        if message == WM_NCHITTEST {
            // When unlocked, treating the transparent client area as a title
            // bar gives native drag behavior without ever activating focus.
            return LRESULT(HTCAPTION as isize);
        }
        unsafe { DefWindowProcW(window, message, wparam, lparam) }
    }

    unsafe fn run_overlay(
        receiver: crossbeam_channel::Receiver<OverlayFrame>,
        stop: Arc<AtomicBool>,
        ready: Sender<anyhow::Result<()>>,
    ) -> anyhow::Result<()> {
        let class_name: Vec<u16> = CLASS_NAME.encode_utf16().chain(Some(0)).collect();
        let window_title: Vec<u16> = WINDOW_TITLE.encode_utf16().chain(Some(0)).collect();
        let module = unsafe { GetModuleHandleW(None) }.context("get LiveSub module handle")?;
        let instance = HINSTANCE(module.0);
        let window_class = WNDCLASSW {
            lpfnWndProc: Some(overlay_window_proc),
            hInstance: instance,
            hCursor: unsafe { LoadCursorW(None, IDC_ARROW) }.unwrap_or_default(),
            lpszClassName: PCWSTR(class_name.as_ptr()),
            ..Default::default()
        };
        unsafe { RegisterClassW(&window_class) };
        let window = unsafe {
            CreateWindowExW(
                WS_EX_LAYERED
                    | WS_EX_TOOLWINDOW
                    | WS_EX_TOPMOST
                    | WS_EX_NOACTIVATE
                    | WS_EX_TRANSPARENT,
                PCWSTR(class_name.as_ptr()),
                PCWSTR(window_title.as_ptr()),
                WS_POPUP,
                0,
                0,
                900,
                190,
                None,
                None,
                Some(instance),
                None,
            )
        }
        .context("create native subtitle overlay")?;
        let _ = ready.try_send(Ok(()));

        let mut previous = OverlayFrame::default();
        let mut message = MSG::default();
        while !stop.load(Ordering::Acquire) {
            while unsafe { PeekMessageW(&mut message, None, 0, 0, PM_REMOVE) }.as_bool() {
                if message.message == WM_QUIT {
                    break;
                }
                unsafe {
                    let _ = TranslateMessage(&message);
                    DispatchMessageW(&message);
                }
            }
            let mut next = None;
            for frame in receiver.try_iter() {
                next = Some(frame);
            }
            if let Some(frame) = next
                && frame != previous
            {
                unsafe { apply_frame(window, &frame) }?;
                previous = frame;
            }
            thread::sleep(Duration::from_millis(16));
        }
        let _ = unsafe { DestroyWindow(window) };
        Ok(())
    }

    unsafe fn apply_frame(
        window: windows::Win32::Foundation::HWND,
        frame: &OverlayFrame,
    ) -> anyhow::Result<()> {
        let current_style = unsafe { GetWindowLongPtrW(window, GWL_EXSTYLE) };
        let updated_style = if frame.locked {
            current_style | WS_EX_TRANSPARENT.0 as isize
        } else {
            current_style & !(WS_EX_TRANSPARENT.0 as isize)
        };
        if updated_style != current_style {
            unsafe { SetWindowLongPtrW(window, GWL_EXSTYLE, updated_style) };
        }

        if !frame.visible || frame.text.trim().is_empty() {
            let _ = unsafe { ShowWindow(window, SW_HIDE) };
            return Ok(());
        }
        unsafe { render_layered(window, frame) }?;
        unsafe {
            SetWindowPos(
                window,
                Some(HWND_TOPMOST),
                frame.x,
                frame.y,
                frame.width,
                frame.height,
                SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        }
        .context("position subtitle overlay")?;
        let _ = unsafe { ShowWindow(window, SW_SHOWNOACTIVATE) };
        Ok(())
    }

    unsafe fn render_layered(
        window: windows::Win32::Foundation::HWND,
        frame: &OverlayFrame,
    ) -> anyhow::Result<()> {
        let width = frame.width.max(240);
        let height = frame.height.max(80);
        let screen_dc = unsafe { GetDC(None) };
        if screen_dc.0.is_null() {
            return Err(anyhow!("GetDC returned null for overlay"));
        }
        let memory_dc = unsafe { CreateCompatibleDC(Some(screen_dc)) };
        if memory_dc.0.is_null() {
            unsafe { ReleaseDC(None, screen_dc) };
            return Err(anyhow!("CreateCompatibleDC returned null for overlay"));
        }

        let mut bitmap_info = BITMAPINFO::default();
        bitmap_info.bmiHeader.biSize =
            size_of::<windows::Win32::Graphics::Gdi::BITMAPINFOHEADER>() as u32;
        bitmap_info.bmiHeader.biWidth = width;
        bitmap_info.bmiHeader.biHeight = -height;
        bitmap_info.bmiHeader.biPlanes = 1;
        bitmap_info.bmiHeader.biBitCount = 32;
        bitmap_info.bmiHeader.biCompression = BI_RGB.0;
        let mut bits: *mut c_void = ptr::null_mut();
        let bitmap = unsafe {
            CreateDIBSection(
                Some(screen_dc),
                &bitmap_info,
                DIB_RGB_COLORS,
                &mut bits,
                None,
                0,
            )
        }
        .context("create overlay alpha bitmap")?;
        let old_bitmap = unsafe { SelectObject(memory_dc, bitmap.into()) };
        let pixels = unsafe {
            std::slice::from_raw_parts_mut(bits.cast::<u8>(), width as usize * height as usize * 4)
        };
        pixels.fill(0);

        let face: Vec<u16> = "Segoe UI".encode_utf16().chain(Some(0)).collect();
        let font = unsafe {
            CreateFontW(
                -(frame.font_size.round() as i32),
                0,
                0,
                0,
                FW_SEMIBOLD.0 as i32,
                0,
                0,
                0,
                DEFAULT_CHARSET,
                OUT_DEFAULT_PRECIS,
                CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY,
                u32::from(DEFAULT_PITCH.0 | FF_SWISS.0),
                PCWSTR(face.as_ptr()),
            )
        };
        let old_font = unsafe { SelectObject(memory_dc, font.into()) };

        let mut text: Vec<u16> = frame.text.encode_utf16().collect();
        let mut measured = RECT {
            left: 0,
            top: 0,
            right: width - 72,
            bottom: height,
        };
        let calculate =
            windows::Win32::Graphics::Gdi::DT_CALCRECT | DT_CENTER | DT_WORDBREAK | DT_NOPREFIX;
        unsafe { DrawTextW(memory_dc, &mut text, &mut measured, calculate) };
        let text_width = (measured.right - measured.left).clamp(1, width - 72);
        let text_height = (measured.bottom - measured.top).clamp(1, height - 24);
        let card_width = (text_width + 38).min(width - 24);
        let card_height = (text_height + 20).min(height - 12);
        let card_left = (width - card_width) / 2;
        let card_bottom = height - 10;
        let card_top = card_bottom - card_height;
        let region = unsafe {
            CreateRoundRectRgn(
                card_left,
                card_top,
                card_left + card_width + 1,
                card_bottom + 1,
                i32::from(frame.corner_radius) * 2,
                i32::from(frame.corner_radius) * 2,
            )
        };
        let brush = unsafe { CreateSolidBrush(COLORREF(0x0008_0808)) };
        let _ = unsafe { FillRgn(memory_dc, region, brush) };

        unsafe {
            SetBkMode(memory_dc, TRANSPARENT);
            SetTextColor(
                memory_dc,
                COLORREF(if frame.tentative {
                    0x00d8_d8d8
                } else {
                    0x00ff_ffff
                }),
            );
        }
        let mut text_rect = RECT {
            left: card_left + 18,
            top: card_top + 9,
            right: card_left + card_width - 18,
            bottom: card_bottom - 9,
        };
        unsafe {
            DrawTextW(
                memory_dc,
                &mut text,
                &mut text_rect,
                DT_CENTER | DT_VCENTER | DT_WORDBREAK | DT_NOPREFIX,
            )
        };

        // GDI writes BGR but leaves DIB alpha at zero. Convert the rendered
        // card to premultiplied BGRA, keeping the background translucent and
        // the subtitle glyphs fully opaque with antialiased coverage.
        premultiply_overlay_pixels(pixels, frame.background_alpha);

        let destination = POINT {
            x: frame.x,
            y: frame.y,
        };
        let size = SIZE {
            cx: width,
            cy: height,
        };
        let source = POINT { x: 0, y: 0 };
        let blend = BLENDFUNCTION {
            BlendOp: AC_SRC_OVER as u8,
            BlendFlags: 0,
            SourceConstantAlpha: 255,
            AlphaFormat: AC_SRC_ALPHA as u8,
        };
        let rendered = unsafe {
            UpdateLayeredWindow(
                window,
                Some(screen_dc),
                Some(&destination),
                Some(&size),
                Some(memory_dc),
                Some(&source),
                COLORREF(0),
                Some(&blend),
                ULW_ALPHA,
            )
        };

        unsafe {
            SelectObject(memory_dc, old_font);
            SelectObject(memory_dc, old_bitmap);
            let _ = DeleteObject(HGDIOBJ(font.0));
            let _ = DeleteObject(HGDIOBJ(brush.0));
            let _ = DeleteObject(HGDIOBJ(region.0));
            let _ = DeleteObject(HGDIOBJ(bitmap.0));
            let _ = DeleteDC(memory_dc);
            ReleaseDC(None, screen_dc);
        }
        rendered.context("upload overlay alpha surface")
    }

    fn premultiply_overlay_pixels(pixels: &mut [u8], background_alpha: u8) {
        for pixel in pixels.chunks_exact_mut(4) {
            let maximum = pixel[0].max(pixel[1]).max(pixel[2]);
            if maximum == 0 {
                continue;
            }
            let coverage = maximum.saturating_sub(8) as u16 * 255 / 247;
            let alpha =
                u16::from(background_alpha) + (255 - u16::from(background_alpha)) * coverage / 255;
            pixel[0] = (u16::from(pixel[0]) * alpha / 255) as u8;
            pixel[1] = (u16::from(pixel[1]) * alpha / 255) as u8;
            pixel[2] = (u16::from(pixel[2]) * alpha / 255) as u8;
            pixel[3] = alpha as u8;
        }
    }

    #[cfg(test)]
    mod tests {
        use super::premultiply_overlay_pixels;

        #[test]
        fn alpha_surface_keeps_clear_pixels_and_opaque_text() {
            let mut pixels = [0, 0, 0, 0, 8, 8, 8, 0, 255, 255, 255, 0];
            premultiply_overlay_pixels(&mut pixels, 190);
            assert_eq!(&pixels[0..4], &[0, 0, 0, 0]);
            assert_eq!(pixels[7], 190);
            assert_eq!(&pixels[8..12], &[255, 255, 255, 255]);
        }
    }
}
