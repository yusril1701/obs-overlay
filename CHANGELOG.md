# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
versi mengikuti [Semantic Versioning](https://semver.org/lang/id/).

## [1.1.0] — 2026-09-29

Menambah sumber video selain OBS/Spout2. Overlay-nya sendiri tidak berubah — yang berubah
hanya dari mana frame datang.

### Ditambahkan

- **NDI** (`ndi-python`): terima sumber video dari mesin lain di jaringan. Bisa memindai
  sumber yang tersedia, mengikuti sumber mana pun kalau nama yang ditulis tidak ada, dan
  mode *low bandwidth* untuk menata parsel lewat koneksi lambat.
- **Screen capture**: tangkap satu monitor, atau sebuah region di dalamnya. Daftar monitor
  mengikuti yang benar-benar tersambung.
- **Image file**: tampilkan PNG, GIF, WebP, JPEG, atau BMP. Animasi GIF/WebP diputar lewat
  `QMovie`; transparansi PNG dipertahankan apa adanya.
- Tab **Source** kini berganti isi mengikuti sumber yang dipilih, dan menyebutkan alasan
  persis kalau sebuah sumber tidak tersedia di mesin ini.
- Pengaman **terowongan tak hingga**: saat `Screen capture` menangkap area yang
  bersinggungan dengan overlay, capture exclusion dinyalakan otomatis.
- CLI: `--source KIND`, `--image PATH`, `--capture-monitor INDEX`, dan
  `--list-senders --source ndi|screen`.
- Tab **About** menampilkan status NDI di samping status SpoutGL.
- **Installer Windows** (`packaging/installer.iss`, Inno Setup 6): pasang seperti
  aplikasi biasa — wizard, pintasan Start Menu, entri di Apps & features, uninstaller.
  Bawaannya per-pengguna, jadi tidak butuh administrator. Opsional: pintasan desktop dan
  jalan otomatis saat masuk Windows. Profil di `%APPDATA%\obs-overlay` tidak ikut
  terhapus kecuali Anda menjawab ya saat ditanya.
- 73 tes baru (381 total), termasuk migrasi profil, kebijakan sambung-ulang,
  penanganan alpha per sumber, dan titik masuk aplikasi.
- Dokumentasi serah-terima: `CLAUDE.md` (invarian yang tidak boleh "diperbaiki", resep
  menambah sumber/setelan, status verifikasi), `docs/WINDOWS_CHECKLIST.md` (verifikasi
  manual yang hanya bisa dilakukan di Windows), dan `docs/ROADMAP.md` (yang bisa
  dikerjakan berikutnya, dan yang sebaiknya tidak).

### Diubah

- `SourceSettings` dipecah menjadi grup per sumber (`spout`, `ndi`, `screen`, `image`),
  sehingga setiap sumber menyimpan setelannya sendiri dan berpindah-pindah tidak
  menghilangkan apa pun. Skema profil naik ke **v3**; profil v1 dan v2 dimigrasi otomatis
  saat dibuka.
- Bawaan alpha kini per sumber: premultiplied untuk Spout (OBS), straight untuk NDI (sesuai
  spesifikasinya).
- Teks "menunggu sumber" pada overlay menyesuaikan sumber yang dipilih, bukan selalu
  menyebut Spout.

### Diperbaiki

- **`.exe` hasil build tidak bisa dijalankan sama sekali.** `__main__.py` memakai impor
  relatif, sedangkan PyInstaller menjalankan berkas itu sebagai skrip biasa tanpa paket
  induk — jadi bundel mati dengan `attempted relative import with no known parent
  package` sebelum menggambar apa pun. Impornya diubah jadi absolut, dan
  `tests/test_entry_point.py` sekarang menjalankan berkas itu persis seperti PyInstaller
  supaya kesalahan yang sama tidak bisa lolos lagi. Bug ini ada sejak rilis 1.0.0.
- `FrameProducer` menyimpan **salinan** setelan sumber, bukan referensi ke objek profil.
  Sebelumnya perbandingan "perlu buka ulang?" membandingkan sebuah objek dengan dirinya
  sendiri, sehingga mengganti nama sender tidak pernah memicu sambung ulang.
- Kegagalan membuka sumber kini dilaporkan lengkap dengan alasannya; sebelumnya
  `close()` menghapus keterangan itu sebelum sempat ditampilkan.
- Notifikasi frame dan permintaan repaint kini di-coalesce, sehingga antrean event Qt
  tidak tumbuh tanpa batas saat thread GUI sedang sibuk.
- `--list-senders --source screen` sempat tidak menampilkan apa pun karena objek
  `QGuiApplication` sementaranya langsung dibuang Python sebelum monitor sempat dibaca.

### Catatan

- Ada kondisi *shutdown* yang belum terpecahkan: dengan QPA headless (`offscreen` /
  `minimal`), `app.exec()` kadang tidak kembali saat overlay terlihat dan feed hidup.
  Coalescing di atas menguranginya secara signifikan tapi tidak menghilangkannya, dan
  penelusuran stack menunjukkan tidak ada kode aplikasi yang memblokir. Belum pernah
  teramati pada jalur Windows yang sesungguhnya.

---

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
