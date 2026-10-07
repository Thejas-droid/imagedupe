"""PyInstaller entry point; freeze_support must run before application imports."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from imagedupe.desktop import main
    raise SystemExit(main())
