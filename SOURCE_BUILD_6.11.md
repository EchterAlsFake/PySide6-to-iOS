# Qt 6.11 and older — historical iOS note

This filename mirrors the companion Android guide's Qt 6.11 chapter. Its NDK
fixes, Python-version matrix and wheel hashes do **not** apply to iOS.

The iOS work here used Qt/PySide **6.12.0** and `pyside6-ios-deploy`. We did not
build or test PySide6 6.11 iOS wheels and do not present a fabricated recipe.

For an older phone, our tested experiment was **Qt 6.12 rebuilt with explicit
iOS 15 compatibility changes**, not an untested downgrade to Qt 6.11. The patch
restores Qt 6.8.3's public Mach-semaphore mutex implementation; borrowing that
implementation does not mean we built a Qt/PySide 6.8 app.

Use [SOURCE_BUILD_6.12.md](SOURCE_BUILD_6.12.md) and
[CURRENT_BUILD_NOTES.md](CURRENT_BUILD_NOTES.md) for the actual recipe/results.
Background: [Qt's iOS announcement](https://www.qt.io/blog/python-mobile-app-development-bringing-pyside6-on-ios).
