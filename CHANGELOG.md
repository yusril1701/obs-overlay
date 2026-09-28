# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
versi mengikuti [Semantic Versioning](https://semver.org/lang/id/).

## [1.0.0] — 2026-09-28

Rilis pertama. Mencakup seluruh Fase 1–4 dari *Project Blueprint: OBS Spout to Python
Transparent Overlay*.

### Fase 1 — jendela tembus pandang dan tembus klik

- Jendela PyQt6 *frameless*, *always on top*, dengan alpha per-piksel.
- Click-through lewat `WS_EX_TRANSPARENT`, dapat diaktifkan/nonaktifkan saat berjalan
  tanpa membuat ulang jendela.
- Tool window (tidak muncul di taskbar/Alt-Tab) dan `WS_EX_NOACTIVATE` (tidak mencuri
  fokus).
- Penegakan ulang *topmost* berkala, karena aplikasi fullscreen bisa merebutnya.
- Opsi menyembunyikan overlay dari screen capture (`WDA_EXCLUDEFROMCAPTURE`), dijaga di
  balik pemeriksaan build Windows 10 2004+.

### Fase 2 — integrasi SpoutGL

- Penerima Spout2 dengan konteks WGL yang dibuat lewat `createOpenGL()`.
- Penanganan resolusi sender yang berubah saat berjalan.
- Deteksi format sender, dengan peringatan eksplisit saat sender tidak membawa alpha.
- Enumerasi sender tanpa perlu konteks GL.
- Sambung ulang otomatis dengan jeda membesar.

### Fase 3 — render real-time

- Thread penerima khusus dengan publikasi *latest-wins*.
- Buffer pool daur ulang; `QImage` dibuat sebagai view tanpa penyalinan.
- Alpha premultiplied ditangani dengan benar (bawaan untuk sumber OBS).
- Mode fit: contain / none / cover / stretch, dengan anchor, zoom, offset, dan cermin.
- HUD statistik: FPS, frame drop, jitter, usia frame terakhir.

### Fase 4 — editor masking interaktif

- Geser, ubah ukuran 8 pegangan, kunci rasio (`Shift`), ubah dari tengah (`Alt`).
- Snapping ke grid, ke parsel lain, dan ke tepi/tengah layar, dengan garis bantu.
- Multi-select, rubber band, align dan distribute.
- Undo/redo 64 langkah.
- Empat bentuk parsel: persegi, sudut tumpul, elips, poligon.
- Mode `Cut` untuk mengurangi parsel di bawahnya (membuat lubang).
- Pembuat tata letak kisi N×M.

### Di luar blueprint

- Panel kontrol bertab untuk seluruh setelan.
- Sistem profil dengan impor/ekspor dan penyimpanan atomik.
- Hotkey global yang dapat diubah, terikat thread agar bertahan saat Qt membuat ulang
  jendela; kegagalan registrasi dilaporkan per-aksi.
- Ikon tray dengan status koneksi dan menu lengkap.
- Sumber pola uji bawaan, sehingga aplikasi bisa dipakai tanpa OBS maupun GPU.
- Pengaman tata letak dan hotkey *panic*.
- Migrasi skema profil dari tata letak era blueprint (`boxes` datar) ke skema v2.
- Mode portable lewat berkas penanda `portable.txt`.
- CLI dengan penimpaan satu kali (`--demo`, `--sender`, `--monitor`, dan lainnya).
- 308 tes otomatis yang berjalan tanpa GPU, tanpa Windows, dan tanpa OBS.
- Build PyInstaller one-dir beserta CI dan alur rilis.

### Catatan teknis

- Renderer memakai backing store raster Qt, bukan `QOpenGLWidget`. Di Windows jalur raster
  memakai `UpdateLayeredWindowIndirect(ULW_ALPHA)` yang memberi alpha per-piksel sekaligus
  hit-testing per-piksel; jalur OpenGL kehilangan yang kedua. Lihat `docs/ARCHITECTURE.md`.
- `SetLayeredWindowAttributes` tidak pernah dipanggil — memanggilnya akan mematikan alpha
  per-piksel Qt secara permanen.
- OpenCV dan Pillow tidak dipakai; numpy dan `QPainter` sudah mencukupi dan menghindari
  konflik plugin platform Qt.
