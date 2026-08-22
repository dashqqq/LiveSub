fn main() {
    #[cfg(windows)]
    {
        let mut resource = winres::WindowsResource::new();
        resource
            .set("ProductName", "LiveSub")
            .set("FileDescription", "LiveSub")
            .set("FileVersion", "0.1.0.0")
            .set("ProductVersion", "0.1.0")
            .set("InternalName", "LiveSub")
            .set("OriginalFilename", "livesub.exe")
            .set_version_info(winres::VersionInfo::FILEVERSION, 0x0000_0001_0000_0000)
            .set_version_info(winres::VersionInfo::PRODUCTVERSION, 0x0000_0001_0000_0000);
        resource
            .compile()
            .expect("failed to compile Windows version resource");
    }
}
